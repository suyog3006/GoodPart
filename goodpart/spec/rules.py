"""Spec-aware acceptance: turn a heatmap into measured regions, map them into zones, apply tolerances.

Zones are polygons in reference-image pixel coordinates, each with its own limits:
    {"name": "A: visible face", "polygon": [[x, y], ...], "max_length_mm": 1.0, "max_area_mm2": 0.5,
     "max_count": 0}
A region outside its zone's tolerance rejects the part. A region inside tolerance is reported only.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import cv2
import numpy as np


@dataclass
class Region:
    bbox: tuple[int, int, int, int]  # x, y, w, h in image pixels
    area_px: float
    length_px: float
    elongation: float
    peak: float
    zone: str | None = None
    area_mm2: float | None = None
    length_mm: float | None = None
    verdict: str = "noted"  # noted | out_of_tolerance
    reason: str = ""
    name: dict | None = None

    def to_dict(self):
        return asdict(self)


def extract_regions(heat: np.ndarray, threshold: float, image_hw: tuple[int, int], min_area_px: int = 12,
                    max_regions: int = 8) -> list[Region]:
    """Threshold the (normalised) heatmap, keep connected components, measure them at image scale."""
    h, w = image_hw
    hm = cv2.resize(np.asarray(heat, np.float32), (w, h), interpolation=cv2.INTER_LINEAR)
    mask = (hm > threshold).astype(np.uint8)
    n, lab, stats_, _ = cv2.connectedComponentsWithStats(mask)
    regions = []
    for i in range(1, n):
        area = float(stats_[i, cv2.CC_STAT_AREA])
        if area < min_area_px:
            continue
        ys, xs = np.nonzero(lab == i)
        pts = np.stack([xs, ys], 1).astype(np.float32)
        (_, _), (rw, rh), _ = cv2.minAreaRect(pts)
        length = float(max(rw, rh, 1.0))
        width = float(max(min(rw, rh), 1.0))
        x, y, bw, bh = (int(v) for v in stats_[i, :4])
        regions.append(Region((x, y, bw, bh), area, length, length / width, float(hm[lab == i].max())))
    regions.sort(key=lambda r: -r.peak)
    return regions[:max_regions]


def zone_of(region: Region, zones: list[dict]) -> dict | None:
    x, y, w, h = region.bbox
    cx, cy = x + w / 2, y + h / 2
    for z in zones:
        if cv2.pointPolygonTest(np.asarray(z["polygon"], np.float32), (float(cx), float(cy)), False) >= 0:
            return z
    return None


def apply_rules(regions: list[Region], zones: list[dict], mm_per_px: float | None,
                default_zone: dict | None = None) -> tuple[bool, list[str]]:
    """Annotate regions with zone, mm sizes and verdict. Returns (any_out_of_tolerance, reasons)."""
    reasons, counts = [], {}
    for r in regions:
        z = zone_of(r, zones) or default_zone
        r.zone = z["name"] if z else None
        if mm_per_px:
            r.length_mm = r.length_px * mm_per_px
            r.area_mm2 = r.area_px * mm_per_px**2
        if not z:
            continue
        counts[r.zone] = counts.get(r.zone, 0) + 1
        problems = []
        if r.length_mm is not None and z.get("max_length_mm") is not None and r.length_mm > z["max_length_mm"]:
            problems.append(f"length {r.length_mm:.1f} mm > {z['max_length_mm']} mm")
        if r.area_mm2 is not None and z.get("max_area_mm2") is not None and r.area_mm2 > z["max_area_mm2"]:
            problems.append(f"area {r.area_mm2:.2f} mm² > {z['max_area_mm2']} mm²")
        if z.get("max_count") is not None and counts[r.zone] > z["max_count"]:
            problems.append(f"{counts[r.zone]} defects > {z['max_count']} allowed")
        if problems:
            r.verdict = "out_of_tolerance"
            r.reason = f"{r.zone}: " + ", ".join(problems)
            reasons.append(r.reason)
        else:
            size = f"{r.length_mm:.1f} mm " if r.length_mm is not None else ""
            r.reason = f"{size}region in {r.zone}, within tolerance"
    return bool(reasons), reasons
