"""End-to-end check of the live API: create a station from good photos, build it, inspect parts.

    python scripts/api_smoke.py --base http://localhost:8000 --category candle --n-good 40
"""
from __future__ import annotations

import argparse
import io
import os
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from goodpart import config  # noqa: E402
from goodpart.data import visa  # noqa: E402


def png(rgb):
    ok, b = cv2.imencode(".png", cv2.cvtColor(np.asarray(rgb), cv2.COLOR_RGB2BGR))
    return io.BytesIO(b.tobytes())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--category", default="candle")
    ap.add_argument("--n-good", type=int, default=40)
    ap.add_argument("--n-test", type=int, default=6)
    a = ap.parse_args()
    h = {"Authorization": f"Bearer {os.environ.get('GOODPART_API_TOKEN', config.API_TOKEN)}"}
    sp = visa.load(a.category)
    sid = requests.post(f"{a.base}/stations", json={"name": f"Smoke test {a.category}"}, headers=h).json()["id"]
    files = [("files", (f"good_{i}.png", png(sp.build_pool[i]), "image/png")) for i in range(a.n_good)]
    up = requests.post(f"{a.base}/stations/{sid}/images", files=files, headers=h).json()["uploaded"]
    print("uploaded", len(up), "flagged", sum(bool(u["flags"]) for u in up))
    t0 = time.time()
    requests.post(f"{a.base}/stations/{sid}/build", headers=h).raise_for_status()
    while True:
        s = requests.get(f"{a.base}/stations/{sid}", headers=h).json()
        if s["status"] in ("ready", "error"):
            break
        time.sleep(2)
    print("build", s["status"], f"{time.time() - t0:.1f}s", s["meta"].get("error", ""))
    if s["status"] != "ready":
        sys.exit(1)
    print("guarantee:", s["station"]["guarantee"])
    labels = sp.test_labels.astype(bool)
    picks = list(np.nonzero(labels)[0][: a.n_test // 2]) + list(np.nonzero(~labels)[0][: a.n_test // 2])
    for i in picks:
        r = requests.post(f"{a.base}/stations/{sid}/inspect", files={"file": ("p.png", png(sp.test[i]), "image/png")},
                          headers=h).json()
        print(f"truth={'defect' if labels[i] else 'good':6s} -> {r['decision']:6s} {r['latency_ms']:.0f} ms "
              f"regions={len(r['regions'])} | {r['reason'][:90]}")
    time.sleep(3)
    rows = requests.get(f"{a.base}/stations/{sid}/inspections", headers=h).json()
    named = [g["name"] for r in rows for g in r["regions"] if g.get("name")]
    print("named regions:", [(n["label"], n["source"]) for n in named][:6])
    c = requests.post(f"{a.base}/stations/{sid}/calibrate", json={"alpha": 0.05, "review_cap": 0.2}, headers=h).json()
    print("recalibrated:", c["guarantee"], "expected review", round(c["expected_review_share"], 3))
    print("summary:", requests.get(f"{a.base}/stations/{sid}/summary", headers=h).json()["counts"])
    print("STATION", sid)


if __name__ == "__main__":
    main()
