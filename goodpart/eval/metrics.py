"""Image AUROC, pixel AUROC, AUPRO (FPR <= 0.3) and bootstrap confidence intervals."""
from __future__ import annotations

import cv2
import numpy as np
from sklearn.metrics import roc_auc_score


def auroc(labels, scores) -> float:
    y = np.asarray(labels).astype(bool)
    if y.all() or not y.any():
        return float("nan")
    return float(roc_auc_score(y, np.asarray(scores)))


def bootstrap_ci(labels, scores, n: int = 1000, seed: int = 0, conf: float = 0.95):
    rng = np.random.default_rng(seed)
    y, s = np.asarray(labels), np.asarray(scores)
    vals = [auroc(y[i], s[i]) for i in (rng.integers(0, len(y), len(y)) for _ in range(n))]
    vals = np.array([v for v in vals if np.isfinite(v)])
    a = (1 - conf) / 2
    return float(np.quantile(vals, a)), float(np.quantile(vals, 1 - a))


def _resize(stack, size, nearest):
    flag = cv2.INTER_NEAREST if nearest else cv2.INTER_AREA
    return np.stack([cv2.resize(np.asarray(a, np.float32), (size, size), interpolation=flag) for a in stack])


def pixel_auroc(masks, maps, size: int = 128) -> float:
    return auroc((_resize(masks, size, True) > 0.5).ravel(), _resize(maps, size, False).ravel())


def aupro(masks, maps, max_fpr: float = 0.3, size: int = 256, n_thresh: int = 500) -> float:
    """Normalised area under the per-region-overlap curve for FPR in [0, max_fpr]."""
    m = _resize(masks, size, True) > 0.5
    s = _resize(maps, size, False)
    if not m.any():
        return float("nan")
    th = np.linspace(s.max(), s.min(), n_thresh)
    neg = np.sort(s[~m])
    fpr = 1.0 - np.searchsorted(neg, th, side="left") / len(neg)
    pro = np.zeros(n_thresh)
    n_regions = 0
    for mi, si in zip(m, s):
        if not mi.any():
            continue
        n, lab = cv2.connectedComponents(mi.astype(np.uint8))
        for r in range(1, n):
            v = np.sort(si[lab == r])
            pro += 1.0 - np.searchsorted(v, th, side="left") / len(v)
            n_regions += 1
    pro /= n_regions
    j = int(np.searchsorted(fpr, max_fpr, side="right"))
    f, p = fpr[:j], pro[:j]
    if j < len(fpr) and j > 0:  # close the curve exactly at max_fpr
        w = (max_fpr - fpr[j - 1]) / max(fpr[j] - fpr[j - 1], 1e-12)
        f, p = np.r_[f, max_fpr], np.r_[p, pro[j - 1] + w * (pro[j] - pro[j - 1])]
    return float(np.trapezoid(p, f) / max_fpr) if len(f) > 1 else float("nan")
