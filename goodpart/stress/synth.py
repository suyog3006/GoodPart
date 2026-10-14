"""Procedural synthetic defects with known masks (noise blobs, scratches, cut-paste patches).

Each defect has a target size (equivalent diameter, pixels) and contrast in [0, 1], so detection
can be studied against size: the probability-of-detection (POD) curve.
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

KINDS = ("blob", "scratch", "cutpaste")


@dataclass
class Defect:
    image: np.ndarray
    mask: np.ndarray
    kind: str
    size_px: float  # measured equivalent diameter sqrt(4 * area / pi)
    contrast: float
    source: int  # index of the good image it was painted on


def smooth_noise(h, w, scale, rng):
    """Multi-octave upsampled noise (a cheap stand-in for Perlin noise)."""
    out = np.zeros((h, w), np.float32)
    for octave, amp in ((scale, 1.0), (scale / 2, 0.5), (scale / 4, 0.25)):
        gh, gw = max(2, int(h / max(octave, 1))), max(2, int(w / max(octave, 1)))
        out += amp * cv2.resize(rng.standard_normal((gh, gw)).astype(np.float32), (w, h),
                                interpolation=cv2.INTER_CUBIC)
    return out / (np.abs(out).max() + 1e-6)


def _centre(fg, h, w, rng, margin):
    if fg is not None and fg.any():
        ys, xs = np.nonzero(fg)
        i = rng.integers(len(ys))
        return int(np.clip(ys[i], margin, h - margin)), int(np.clip(xs[i], margin, w - margin))
    return int(rng.integers(margin, h - margin)), int(rng.integers(margin, w - margin))


def _blob(h, w, d, c, rng):
    yy, xx = np.ogrid[:h, :w]
    dist = np.sqrt((yy - c[0]) ** 2 + (xx - c[1]) ** 2) / max(d / 2, 1)
    return (1.0 - dist + 0.35 * smooth_noise(h, w, max(d / 2, 4), rng)) > 0


def _scratch(h, w, length, width, c, rng):
    m = np.zeros((h, w), np.uint8)
    a = rng.uniform(0, np.pi)
    bend = rng.uniform(-0.3, 0.3) * length
    t = np.linspace(-0.5, 0.5, 32)
    off = (0.25 - t**2) * bend
    xs = c[1] + t * length * np.cos(a) - off * np.sin(a)
    ys = c[0] + t * length * np.sin(a) + off * np.cos(a)
    cv2.polylines(m, [np.stack([xs, ys], 1).round().astype(np.int32)], False, 1,
                  thickness=max(1, int(round(width))), lineType=cv2.LINE_8)
    return m > 0


def paint(image, kind, size_px, contrast, rng, fg=None, source=-1) -> Defect:
    h, w = image.shape[:2]
    c = _centre(fg, h, w, rng, margin=int(size_px) + 2)
    base = image.astype(np.float32)
    img = base.copy()
    sign = rng.choice([-1.0, 1.0])
    if kind == "blob":
        mask = _blob(h, w, size_px, c, rng)
        tint = rng.uniform(0.6, 1.0, 3) * 255 * contrast * sign
        tex = 0.7 + 0.3 * smooth_noise(h, w, 3, rng)[..., None]
        img = np.where(mask[..., None], np.clip(base + tint * tex, 0, 255), base)
    elif kind == "scratch":
        width = max(1.5, size_px / 6)
        length = max(size_px, np.pi * size_px**2 / (4 * width))  # same equivalent area as a disc of size_px
        mask = _scratch(h, w, length, width, c, rng)
        img = np.where(mask[..., None], np.clip(base + sign * 255 * contrast, 0, 255), base)
    elif kind == "cutpaste":
        mask = _blob(h, w, size_px, c, rng)
        dy, dx = int(rng.integers(-h // 3, h // 3)), int(rng.integers(-w // 3, w // 3))
        src = np.roll(base, (dy, dx), (0, 1))
        src = np.clip(src * (1 + contrast * rng.uniform(-0.5, 0.5)) + contrast * rng.uniform(-60, 60), 0, 255)
        img = np.where(mask[..., None], src, base)
    else:
        raise ValueError(kind)
    soft = cv2.GaussianBlur(mask.astype(np.float32), (0, 0), 0.8)[..., None]
    out = (soft * img + (1 - soft) * base).round().astype(np.uint8)
    return Defect(out, mask, kind, float(np.sqrt(4 * mask.sum() / np.pi)), float(contrast), source)


def grid(images, sizes_px, contrasts, per_cell, seed=0, kinds=KINDS, fg_masks=None):
    """Synthetic defects across size x contrast x kind, painted on randomly chosen good images."""
    rng = np.random.default_rng(seed)
    for s in sizes_px:
        for c in contrasts:
            for k in kinds:
                for _ in range(per_cell):
                    i = int(rng.integers(len(images)))
                    yield paint(np.asarray(images[i]), k, s, c, rng, None if fg_masks is None else fg_masks[i], i)
