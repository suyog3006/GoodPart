"""Make evaluated VisA stations available to the live API (so visitors can upload photos to them)
and seed each with real inspections of held-out test images.

    python scripts/seed_live.py --categories candle pcb1 --n 40 --base http://localhost:8000
"""
from __future__ import annotations

import argparse
import glob
import io
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from goodpart import config  # noqa: E402
from goodpart.data import visa  # noqa: E402
from goodpart.eval.run import make_backbones  # noqa: E402
from goodpart.station import Station  # noqa: E402
from goodpart.stress import pod  # noqa: E402

# Sample products shown to every visitor: (name, noun used in sentences, one-line description).
CATALOG = {
    "candle": ("Candles", "tray of candles", "Four white tea-light candles on a dark tray."),
    "capsules": ("Capsules", "tray of capsules", "About 20 green soft-gel capsules on a grey tray."),
    "cashew": ("Cashew nut", "cashew nut", "A single cashew on a dark textured surface."),
    "chewinggum": ("Chewing gum", "piece of chewing gum", "A single white gum pellet on a dark surface."),
    "fryum": ("Wheel snack", "wheel snack", "A wheel-shaped fried snack (fryum) on a green surface."),
    "macaroni1": ("Macaroni, tray A", "macaroni tray", "Four elbow macaroni neatly placed on a green tray."),
    "macaroni2": ("Macaroni, tray B", "macaroni tray", "Four elbow macaroni on a textured green surface."),
    "pcb1": ("Ultrasonic sensor board, front", "sensor board", "HC-SR04 ultrasonic distance sensor, front side."),
    "pcb2": ("Ultrasonic sensor board, back", "sensor board", "HC-SR04 ultrasonic distance sensor, component side."),
    "pcb3": ("IR obstacle sensor board", "sensor board", "Infrared obstacle-detection sensor module."),
    "pcb4": ("USB charger board", "charger board", "Micro-USB lithium battery charging module."),
    "pipe_fryum": ("Pipe snack", "pipe snack", "A tube-shaped fried snack (fryum) on a black surface."),
}
DEFAULT_CFG = {"dino": "facebook/dinov2-base", "dino_size": 672, "wrn_size": 320}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--categories", nargs="*", default=list(CATALOG))
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--base", default="http://localhost:8000")
    a = ap.parse_args()
    h = {"Authorization": f"Bearer {os.environ.get('GOODPART_API_TOKEN', config.API_TOKEN)}"}
    bb = make_backbones(DEFAULT_CFG)
    out_dir = config.STORE_DIR / "stations"
    con = sqlite3.connect(config.STORE_DIR / "goodpart.db", timeout=30)
    new = []
    for cat in a.categories:
        sid = f"visa-{cat}"
        name, noun, desc = CATALOG[cat]
        row = con.execute("SELECT meta FROM station WHERE id=?", (sid,)).fetchone()
        if row and (out_dir / f"{sid}.pkl").exists():
            # Already registered: refresh the name and description, keep its inspection history.
            meta = {**json.loads(row[0] or "{}"), "noun": noun, "description": desc, "sample": True}
            con.execute("UPDATE station SET name=?, meta=? WHERE id=?", (name, json.dumps(meta), sid))
            con.commit()
            print(sid, "renamed to", name, flush=True)
            continue
        new.append(cat)
        pkl = sorted(glob.glob(str(config.STORE_DIR / "stations" / f"visa_{cat}_k*.pkl")),
                     key=lambda p: int(p.rsplit("_k", 1)[1].split(".")[0]))[-1]
        k = int(pkl.rsplit("_k", 1)[1].split(".")[0])
        st = Station.load(Path(pkl), bb, config.device())
        sp = visa.load(cat)
        if not getattr(st, "has_region_threshold", False):
            st.fit_region_threshold(sp.calibration)
        st.save(out_dir / f"{sid}.pkl")
        m = pd.DataFrame(st.defects_meta)
        m["hit"] = st.synth_scores >= st.calibration.t_low
        f = pod.fit(m.size_px, m.hit)
        meta = {"n_build": k, "n_cal": st.calibration.n_cal, "calibration": st.calibration.to_dict(),
                "selection": st.selection, "a90_95_px": f.get("a90_95"), "device": config.device_label(),
                "source": "VisA (CC BY 4.0), evaluated station", "noun": noun, "description": desc, "sample": True}
        con.execute("DELETE FROM inspection WHERE station=?", (sid,))
        con.execute("INSERT OR REPLACE INTO station (id, name, created, status, mm_per_px, zones, meta) "
                    "VALUES (?,?,?,?,?,?,?)", (sid, name, time.time(), "ready", None, "[]",
                                              json.dumps(meta, default=float)))
        # Reference image for the zone editor.
        ref_dir = config.STORE_DIR / "images" / sid / "good"
        ref_dir.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(ref_dir / "reference.png"), cv2.cvtColor(np.asarray(sp.build_pool[0]), cv2.COLOR_RGB2BGR))
        con.execute("INSERT OR REPLACE INTO image VALUES (?,?,?,?,?)",
                    (f"{sid}-ref", sid, str(ref_dir / "reference.png"), "good", json.dumps({"flags": []})))
        con.commit()
        print(sid, "registered from", Path(pkl).name, flush=True)

    # Seed new products through the real API so the records are identical to live uploads.
    for cat in new:
        sid = f"visa-{cat}"
        sp = visa.load(cat)
        rng = np.random.default_rng(1)
        bad, good = np.nonzero(sp.test_labels)[0], np.nonzero(~sp.test_labels.astype(bool))[0]
        idx = np.r_[rng.choice(bad, a.n // 2, replace=False), rng.choice(good, a.n - a.n // 2, replace=False)]
        rng.shuffle(idx)
        for i in idx:
            ok, buf = cv2.imencode(".png", cv2.cvtColor(np.asarray(sp.test[i]), cv2.COLOR_RGB2BGR))
            r = requests.post(f"{a.base}/stations/{sid}/inspect", headers=h,
                              files={"file": ("part.png", io.BytesIO(buf.tobytes()), "image/png")})
            r.raise_for_status()
        print(sid, "seeded with", len(idx), "inspections", flush=True)


if __name__ == "__main__":
    main()
