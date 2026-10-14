"""M0 check: N concurrent defect-naming requests on real VisA defect crops, per VLM backend.

    python scripts/vlm_check.py --modes vllm tokenfactory --n 8
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from goodpart import config  # noqa: E402
from goodpart.data import visa  # noqa: E402
from goodpart.describe import vlm  # noqa: E402


def crops(n: int, cats=("candle", "pcb1", "cashew", "capsules")):
    out = []
    for c in cats:
        sp = visa.load(c)
        for i in np.nonzero(sp.test_labels)[0][: n // len(cats) + 1]:
            m = np.asarray(sp.test_masks[i]).astype(np.uint8)
            x, y, w, h = cv2.boundingRect(m)
            pad = max(24, max(w, h) // 2)
            img = np.asarray(sp.test[i])
            y0, y1, x0, x1 = max(0, y - pad), min(768, y + h + pad), max(0, x - pad), min(768, x + w + pad)
            crop = img[y0:y1, x0:x1]
            heat = cv2.GaussianBlur(m[y0:y1, x0:x1].astype(np.float32), (0, 0), 3)
            out.append((c, sp.test_files[i], crop, vlm.overlay(crop, heat, 0, max(heat.max(), 1e-3))))
    return out[:n]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--modes", nargs="*", default=["vllm", "tokenfactory"])
    ap.add_argument("--n", type=int, default=8)
    a = ap.parse_args()
    items = crops(a.n)
    report = {}
    for mode in a.modes:
        def one(it):
            try:
                ans, meta = vlm.ask([it[2], it[3]], vlm.NAME_PROMPT, mode)
                return {"file": it[1], "label": ans.get("label"), "valid": ans.get("label") in vlm.LABELS,
                        "description": ans.get("description"), **meta}
            except Exception as e:
                return {"file": it[1], "valid": False, "error": f"{type(e).__name__}: {e}"[:200]}

        t0 = time.perf_counter()
        with ThreadPoolExecutor(len(items)) as ex:
            res = list(ex.map(one, items))
        wall = time.perf_counter() - t0
        lat = [r["latency_s"] for r in res if "latency_s" in r]
        report[mode] = {"n": len(res), "valid_json_label": sum(r["valid"] for r in res), "wall_s": round(wall, 2),
                        "median_latency_s": float(np.median(lat)) if lat else None, "results": res}
        print(mode, json.dumps({k: v for k, v in report[mode].items() if k != "results"}))
        for r in res:
            print("   ", r.get("label"), "|", (r.get("description") or r.get("error", ""))[:90])
    out = config.RESULTS_DIR / "vlm_check.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1, default=str))


if __name__ == "__main__":
    main()
