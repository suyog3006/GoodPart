"""Record real results from the GPU for the web app's demo mode (web/public/demo/).

    python scripts/export_demo.py --stations candle pcb1 --n 40 --out /workspace/goodpart/demo_export

Everything exported is produced by the same pipeline as the live API: decisions, regions and
defect names come from the stored stations and the VLM. Nothing is hand-edited.
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from goodpart import config, pipeline  # noqa: E402
from goodpart.data import visa  # noqa: E402
from goodpart.describe import vlm  # noqa: E402
from goodpart.drift import monitor  # noqa: E402
from goodpart.eval.run import make_backbones  # noqa: E402
from goodpart.station import Station  # noqa: E402
from goodpart.stress import pod, synth  # noqa: E402


def jpg(path: Path, rgb: np.ndarray, side: int = 768, q: int = 85):
    path.parent.mkdir(parents=True, exist_ok=True)
    if rgb.shape[0] != side:
        rgb = cv2.resize(rgb, (side, side), interpolation=cv2.INTER_AREA)
    cv2.imwrite(str(path), cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, q])


def clean(o):
    return json.loads(json.dumps(o, default=lambda x: float(x) if np.isscalar(x) else str(x)).replace("Infinity", "null").replace("NaN", "null"))


def export_station(cat: str, res_dir: Path, out: Path, n: int, bb, cfg) -> dict:
    pkl = sorted(glob.glob(str(config.STORE_DIR / "stations" / f"visa_{cat}_k*.pkl")),
                 key=lambda p: int(p.rsplit("_k", 1)[1].split(".")[0]))[-1]
    st = Station.load(Path(pkl), bb, config.device())
    k = int(pkl.rsplit("_k", 1)[1].split(".")[0])
    summ = json.loads((res_dir / f"{cat}_k{k}" / "summary.json").read_text())
    sid = f"visa-{cat}"
    sp = visa.load(cat)
    if not getattr(st, "has_region_threshold", False):
        print(cat, "region threshold", st.fit_region_threshold(sp.calibration), flush=True)
    rng = np.random.default_rng(1)
    bad = np.nonzero(sp.test_labels)[0]
    good = np.nonzero(~sp.test_labels.astype(bool))[0]
    idx = np.r_[rng.choice(bad, n // 2, replace=False), rng.choice(good, n - n // 2, replace=False)]
    rng.shuffle(idx)
    items = []
    t_base = time.time() - 3600
    for j, i in enumerate(idx):
        img = np.asarray(sp.test[i])
        t0 = time.perf_counter()
        r = pipeline.decide(st, img)
        lat = (time.perf_counter() - t0) * 1000
        heat = r["heat"]
        lo, vmax = st.region_threshold * 0.5, st.region_threshold * 2
        regs = [g.to_dict() for g in r["regions"]]
        h, w = img.shape[:2]
        for g in regs[:3]:
            x, y, bw, bh = g["bbox"]
            pad = max(24, int(0.5 * max(bw, bh)))
            x0, y0, x1, y1 = max(0, x - pad), max(0, y - pad), min(w, x + bw + pad), min(h, y + bh + pad)
            hm = cv2.resize(heat, (w, h))[y0:y1, x0:x1]
            g["name"] = vlm.name_defect(img[y0:y1, x0:x1], vlm.overlay(img[y0:y1, x0:x1], hm, lo, vmax),
                                        None, g["elongation"])
        iid = f"{cat}-{j:03d}"
        jpg(out / sid / f"{iid}.jpg", img)
        jpg(out / sid / f"{iid}_overlay.jpg", vlm.overlay(img, heat, lo, vmax))
        items.append({"id": iid, "station": sid, "created": t_base + j * 60, "score": r["score"], "z": r["z"],
                      "decision": r["decision"], "band": r["band"], "reason": r["reason"], "regions": regs,
                      "device": config.device_label(), "latency_ms": lat,
                      "image_url": f"/demo/{sid}/{iid}.jpg", "overlay_url": f"/demo/{sid}/{iid}_overlay.jpg",
                      "truth": "anomaly" if sp.test_labels[i] else "good", "source_file": sp.test_files[i]})
        print(cat, j, r["decision"], f"{lat:.0f} ms", flush=True)
    # Synthetic gallery from the stress pool (fresh draws, scored now).
    defects = list(synth.grid(list(sp.stress), [6, 16, 45], [0.1, 0.25, 0.5], 1, seed=7))
    out_s = st.run([d.image for d in defects], maps=False)
    gal = []
    for g, (d, s) in enumerate(zip(defects, out_s.score)):
        ys, xs = np.nonzero(d.mask)
        cy, cx = int(ys.mean()), int(xs.mean())
        half = int(max(48, d.size_px * 1.5))
        crop = d.image[max(0, cy - half):cy + half, max(0, cx - half):cx + half]
        jpg(out / sid / f"synth_{g:02d}.jpg", crop, side=192)
        gal.append({"image": f"/demo/{sid}/synth_{g:02d}.jpg", "kind": d.kind, "size_px": d.size_px,
                    "contrast": d.contrast, "hit": bool(s >= st.calibration.t_low)})
    ref = np.asarray(sp.build_pool[0])
    jpg(out / f"reference_{sid}.jpg", ref)
    m = pd.DataFrame(st.defects_meta)
    m["hit"] = st.synth_scores >= st.calibration.t_low
    f = pod.fit(m.size_px, m.hit)
    counts = pd.Series([i["decision"] for i in items]).value_counts().to_dict()
    row = summ["row"]
    meta = {"n_build": k, "calibration": st.calibration.to_dict(), "a90_95_px": f.get("a90_95"),
            "selection": st.selection, "device": config.device_label(), "drift": "ok"}
    detail = {"id": sid, "name": f"VisA {cat}", "status": "ready", "mm_per_px": None, "zones": [], "counts": counts,
              "meta": meta,
              "station": {"active": list(st.active), "selection": st.selection, "calibration": st.calibration.to_dict(),
                          "guarantee": st.calibration.guarantee_text(),
                          "pod": {**f, "curve": pod.curve(f, np.geomspace(2, 160, 48))}, "mm_per_px": None,
                          "a90_95_mm": None, "scores": {"calibration": st.cal_scores.tolist(),
                                                        "synthetic": st.synth_scores.tolist()},
                          "timings": st.timings},
              "pod_agreement": summ["pod_agreement"], "gallery": gal, "eval_row": row}
    (out / f"station_{sid}.json").write_text(json.dumps(clean(detail)))
    (out / f"inspections_{sid}.json").write_text(json.dumps(clean(items[::-1])))
    return {"id": sid, "name": f"VisA {cat}", "status": "ready", "mm_per_px": None, "counts": counts, "meta": meta}


def failures(res_dir: Path, out: Path, per_cat: int = 2) -> list[dict]:
    """Missed defects and false rejects of the full stations, with heatmaps from the evaluation run."""
    rows = []
    for d in sorted(res_dir.glob("*_k*")):
        cat, k = d.name.rsplit("_k", 1)
        if not (d / "per_image.csv").exists():
            continue
        same = sorted(res_dir.glob(f"{cat}_k*"), key=lambda p: int(p.name.rsplit("_k", 1)[1]))
        if d != same[-1]:
            continue
        pi = pd.read_csv(d / "per_image.csv")
        maps = np.load(d / "test_maps.npy")
        sp = visa.load(cat)
        sel = [("missed defect", pi[(pi.label == "anomaly") & (pi.decision == "pass")].sort_values("score").head(per_cat)),
               ("false reject", pi[(pi.label == "good") & (pi.decision == "reject")].sort_values("score", ascending=False).head(per_cat))]
        for kind, df in sel:
            for i, r in df.iterrows():
                img = np.asarray(sp.test[i])
                hm = maps[i].astype(np.float32)
                name = f"fail_{cat}_{i}"
                jpg(out / "failures" / f"{name}.jpg", vlm.overlay(img, hm, 1.5, 6.0), side=384)
                rows.append({"category": cat, "file": r["file"], "kind": kind, "score": float(r["score"]),
                             "image": f"/demo/failures/{name}.jpg", "overlay": f"/demo/failures/{name}.jpg"})
    return rows


def guarantee_drift(res_dir: Path) -> list[dict]:
    """Would the drift guard have flagged the test split? KS test of test-good scores vs calibration."""
    out = []
    for d in sorted(res_dir.glob("*_k*")):
        if not (d / "summary.json").exists():
            continue
        s = json.loads((d / "summary.json").read_text())
        cal = s["calibration"]
        test_good = np.array(s["scores"]["test_good"])
        res = monitor.test(test_good[test_good <= (cal["t_high"] or np.inf)],
                           np.array(s["scores"]["calibration"])[np.array(s["scores"]["calibration"]) <= (cal["t_high"] or np.inf)])
        out.append({"station": d.name, "false_reject_rate": s["row"]["false_reject_rate"],
                    "alpha_guaranteed": cal["alpha_guaranteed"], **res})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stations", nargs="*", default=["candle", "pcb1"])
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--name", default="visa_full")
    ap.add_argument("--out", default=str(config.ROOT / "demo_export"))
    a = ap.parse_args()
    import yaml

    cfg = yaml.safe_load(open(config.ROOT / "configs" / "eval_visa.yaml"))
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    res_dir = config.RESULTS_DIR / a.name
    bb = make_backbones(cfg)
    stations = [export_station(c, res_dir, out, a.n, bb, cfg) for c in a.stations]
    (out / "stations.json").write_text(json.dumps(clean(stations)))
    (out / "health.json").write_text(json.dumps({"device": config.device_label()}))
    zs = config.RESULTS_DIR / "zeroshot" / "zeroshot_vllm.csv"
    bench = config.RESULTS_DIR / "benchmark.json"
    few = res_dir / "fewshot.csv"
    fewshot = []
    if few.exists():
        f = pd.read_csv(few)
        fewshot = [{"k": str(k), "A": g.A.mean(), "B": g.B.mean(), "AB": g.AB.mean()}
                   for k, g in f.groupby("k_label", sort=False)]
    bundle = {"results": pd.read_csv(res_dir / "results.csv").to_dict("records"),
              "baselines": pd.read_csv(res_dir / "baselines.csv").to_dict("records"),
              "zeroshot": pd.read_csv(zs).to_dict("records") if zs.exists() else [],
              "benchmark": json.loads(bench.read_text()) if bench.exists() else None,
              "fewshot": fewshot, "failures": failures(res_dir, out), "guarantee_drift": guarantee_drift(res_dir)}
    (out / "eval.json").write_text(json.dumps(clean(bundle)))
    print("exported to", out)


if __name__ == "__main__":
    main()
