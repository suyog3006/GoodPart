"""Anomaly detectors trained on good images only.

Detector A: patch kNN on DINOv2 features (AnomalyDINO-style, strong few-shot).
Detector B: PatchCore on WideResNet-50 (Roth et al., CVPR 2022).
Baseline:   golden-template difference.

`score(images)` returns per-image scores and patch-level maps at feature resolution.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np
import torch
import torch.nn.functional as F


def batched(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i : i + n]


def _sync():
    if torch.cuda.is_available():
        torch.cuda.synchronize()


def nn_search(q: torch.Tensor, bank: torch.Tensor, k: int = 1, cosine: bool = False, max_elems: int = 2**31):
    """k nearest bank rows for each query row. Chunked so the distance matrix fits in memory."""
    chunk = max(1, min(len(q), max_elems // max(1, bank.shape[0])))
    ds, ix = [], []
    for qc in batched(q, chunk):
        if cosine:
            d = 1.0 - (qc.to(bank.dtype) @ bank.T).float()
        else:
            d = torch.cdist(qc.float(), bank.float())
        v, i = d.topk(k, dim=1, largest=False)
        ds.append(v)
        ix.append(i)
    return torch.cat(ds), torch.cat(ix)


def greedy_coreset(x: torch.Tensor, n_select: int, proj_dim: int = 128, seed: int = 0) -> torch.Tensor:
    """Greedy k-center selection on a random projection (PatchCore's coreset subsampling)."""
    n = x.shape[0]
    if n_select >= n:
        return torch.arange(n, device=x.device)
    g = torch.Generator().manual_seed(seed)
    proj = (torch.randn(x.shape[1], proj_dim, generator=g) / proj_dim**0.5).to(x.device)
    z = x.float() @ proj
    sel = torch.empty(n_select, dtype=torch.long, device=x.device)
    sel[0] = int(torch.randint(n, (1,), generator=g))
    mind = ((z - z[sel[0]]) ** 2).sum(1)
    for j in range(1, n_select):
        nxt = torch.argmax(mind)
        sel[j] = nxt
        mind = torch.minimum(mind, ((z - z[nxt]) ** 2).sum(1))
    return sel


def upsample(maps: np.ndarray, size: int, sigma: float = 4.0) -> np.ndarray:
    """(B, h, w) patch maps -> (B, size, size), bilinear then Gaussian-smoothed (on GPU if available)."""
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    t = torch.from_numpy(np.asarray(maps, np.float32)).to(dev).unsqueeze(1)
    t = F.interpolate(t, size=(size, size), mode="bilinear", align_corners=False)
    if sigma > 0:
        r = int(4 * sigma + 0.5)
        xs = torch.arange(-r, r + 1, device=dev, dtype=torch.float32)
        k = torch.exp(-(xs**2) / (2 * sigma**2))
        k = (k / k.sum()).view(1, 1, 1, -1)
        t = F.conv2d(F.pad(t, (r, r, 0, 0), mode="reflect"), k)
        t = F.conv2d(F.pad(t, (0, 0, r, r), mode="reflect"), k.transpose(2, 3))
    return t.squeeze(1).cpu().numpy()


@dataclass
class Scores:
    scores: np.ndarray  # (B,)
    maps: np.ndarray  # (B, h, w)
    seconds: float


class PatchKNN:
    """Detector A. Patch score = cosine distance to the nearest good patch; image score = mean of
    the top 1% patch scores. Optional foreground masking via the first principal component."""

    name = "A"

    def __init__(self, backbone, top_fraction=0.01, mask_background=False, max_bank=None, batch_size=32):
        self.bb, self.top_fraction, self.mask_background = backbone, top_fraction, mask_background
        self.max_bank, self.batch_size = max_bank, batch_size
        self.bank = self.pc = self.pc_mean = None
        self.pc_sign = 1.0

    def features(self, images):
        return torch.cat([self.bb(b) for b in batched(images, self.batch_size)])

    def _fg(self, f):
        if not self.mask_background or self.pc is None:
            return torch.ones(f.shape[:-1], dtype=torch.bool, device=f.device)
        m = (((f - self.pc_mean) @ self.pc) * self.pc_sign) > 0
        return F.max_pool2d(m.float().unsqueeze(1), 3, 1, 1).squeeze(1) > 0

    def fit(self, images):
        f = self.features(images)
        if self.mask_background:
            flat = f.reshape(-1, f.shape[-1])
            sub = flat[torch.randperm(len(flat), device=flat.device)[:200_000]]
            self.pc_mean = sub.mean(0)
            self.pc = torch.pca_lowrank(sub - self.pc_mean, q=1, center=False)[2][:, 0]
            proj = (f - self.pc_mean) @ self.pc
            border = torch.cat([proj[:, 0], proj[:, -1], proj[:, :, 0], proj[:, :, -1]], 1)
            self.pc_sign = -1.0 if border.mean() > 0 else 1.0
        bank = f[self._fg(f)]
        if self.max_bank and len(bank) > self.max_bank:
            bank = bank[greedy_coreset(bank, self.max_bank)]
        self.bank = bank.to(torch.bfloat16 if bank.is_cuda else torch.float32).contiguous()
        return self

    @torch.no_grad()
    def score(self, images) -> Scores:
        t0 = time.perf_counter()
        f = self.features(images)
        b, h, w, c = f.shape
        d, _ = nn_search(f.reshape(-1, c), self.bank, cosine=True)
        maps = d[:, 0].reshape(b, h, w)
        maps = torch.where(self._fg(f), maps, torch.zeros_like(maps))
        k = max(1, round(h * w * self.top_fraction))
        s = maps.reshape(b, -1).topk(k, 1).values.mean(1)
        _sync()
        return Scores(s.cpu().numpy(), maps.cpu().numpy(), time.perf_counter() - t0)


class PatchCore:
    """Detector B. Coreset memory bank; image score = max patch distance re-weighted by how
    isolated the matched memory entry is (softmax form, as in anomalib)."""

    name = "B"

    def __init__(self, backbone, coreset_ratio=0.1, max_bank=None, reweight_k=9, batch_size=32):
        self.bb, self.ratio, self.max_bank = backbone, coreset_ratio, max_bank
        self.reweight_k, self.batch_size = reweight_k, batch_size
        self.bank = None

    def features(self, images):
        return torch.cat([self.bb(b) for b in batched(images, self.batch_size)])

    def fit(self, images):
        flat = self.features(images)
        flat = flat.reshape(-1, flat.shape[-1])
        n = max(1, int(len(flat) * self.ratio))
        if self.max_bank:
            n = min(n, self.max_bank)
        self.bank = flat[greedy_coreset(flat, n)].contiguous()
        return self

    @torch.no_grad()
    def score(self, images) -> Scores:
        t0 = time.perf_counter()
        f = self.features(images)
        b, h, w, c = f.shape
        flat = f.reshape(-1, c)
        d, idx = nn_search(flat, self.bank)
        maps = d[:, 0].reshape(b, h, w)
        per = maps.reshape(b, -1)
        arg = per.argmax(1)
        s_star = per.max(1).values
        q = flat.reshape(b, h * w, c)[torch.arange(b), arg]
        m_star = self.bank[idx[:, 0].reshape(b, -1)[torch.arange(b), arg]]
        k = min(self.reweight_k + 1, len(self.bank))
        _, nb = nn_search(m_star, self.bank, k=k)  # neighbours of m*, including m* itself
        dist = torch.linalg.norm(self.bank[nb] - q[:, None], dim=-1)
        s = (1.0 - torch.softmax(dist, 1)[:, 0]) * s_star
        _sync()
        return Scores(s.cpu().numpy(), maps.cpu().numpy(), time.perf_counter() - t0)


class GoldenTemplate:
    """Baseline: per-pixel z-score against the mean/std of good images (grey, blurred)."""

    name = "golden"

    def __init__(self, size=256):
        self.size = size

    def _prep(self, images):
        import cv2

        return np.stack([cv2.GaussianBlur(cv2.cvtColor(cv2.resize(np.asarray(im), (self.size, self.size),
                         interpolation=cv2.INTER_AREA), cv2.COLOR_RGB2GRAY).astype(np.float32), (0, 0), 2)
                         for im in images])

    def fit(self, images):
        x = self._prep(images)
        self.mean, self.std = x.mean(0), x.std(0) + 5.0
        return self

    def score(self, images) -> Scores:
        t0 = time.perf_counter()
        maps = np.abs(self._prep(images) - self.mean) / self.std
        flat = maps.reshape(len(maps), -1)
        s = np.sort(flat, 1)[:, -max(1, flat.shape[1] // 100):].mean(1)
        return Scores(s, maps, time.perf_counter() - t0)
