"""Inspection of one image (pipeline D): score, band, regions, spec rules, decision and reason.

Shared by the API and the demo export so both produce identical decisions.
"""
from __future__ import annotations

import numpy as np

from goodpart.spec import rules

SIZE = 768


def decide(station, img: np.ndarray, zones: list[dict] | None = None, mm_per_px: float | None = None) -> dict:
    """`img` is RGB at SIZE x SIZE. `mm_per_px` refers to that resolution."""
    zones = zones or []
    out = station.run([img], maps=True)
    score = float(out.score[0])
    heat = out.maps[0]
    cal = station.calibration
    band = str(cal.decide(np.array([score]))[0])
    regions = rules.extract_regions(heat, station.region_threshold, (SIZE, SIZE)) if band != "pass" else []
    out_of_tol, reasons = rules.apply_rules(regions, zones, mm_per_px)
    if out_of_tol:
        decision, reason = "reject", "; ".join(reasons)
    elif band != "pass" and zones and mm_per_px and regions:
        decision = "pass"
        reason = "Anomalies found but within spec: " + "; ".join(r.reason for r in regions)
    else:
        decision = band
        reason = {
            "pass": f"Score {score:.2f} is below the pass threshold {cal.t_low:.2f}.",
            "review": f"Score {score:.2f} is between {cal.t_low:.2f} and {cal.t_high:.2f}, so an inspector should look.",
            "reject": f"Score {score:.2f} is above the reject threshold {cal.t_high:.2f}.",
        }[band]
        if regions:
            r0 = regions[0]
            size = f"{r0.length_mm:.1f} mm" if r0.length_mm is not None else f"{r0.length_px:.0f} px"
            reason += f" Largest unusual region: {size} long{f' in {r0.zone}' if r0.zone else ''}."
    return {"score": score, "z": {k: float(v[0]) for k, v in out.z.items()}, "band": band, "decision": decision,
            "reason": reason, "regions": regions, "heat": heat, "seconds": sum(out.seconds.values())}
