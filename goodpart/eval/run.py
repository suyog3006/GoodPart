"""Full VisA evaluation: build, calibrate, inspect the test split, compare baselines, fit POD curves.

    python -m goodpart.eval.run --config configs/eval_visa.yaml [--categories candle pcb1]

Writes results/<name>/{results.csv, baselines.csv, <category>/...}. Test data never touches
thresholds or station selection.
"""
from __future__ import annotations

import argparse
import json
import time

import cv2
import numpy as np
import pandas as pd
import torch
import yaml

from goodpart import config
from goodpart.calibrate import stats as st
from goodpart.data import visa
from goodpart.eval.metrics import aupro, auroc, bootstrap_ci, pixel_auroc
from goodpart.models.backbones import DinoV2, WideResNet50
from goodpart.models.detectors import GoldenTemplate
from goodpart.station import Station
from goodpart.stress import pod


def largest_region_diameter(mask) -> float:
    n, _, s, _ = cv2.connectedComponentsWithStats(np.asarray(mask, np.uint8))
    return 0.0 if n <= 1 else float(np.sqrt(4 * s[1:, cv2.CC_STAT_AREA].max() / np.pi))


def make_backbones(cfg):
    dev = config.device()
    return {"A": DinoV2(cfg["dino"], cfg["dino_size"], dev), "B": WideResNet50(cfg["wrn_size"], dev)}


def evaluate(cat: str, cfg: dict, backbones: dict, out_dir, k_build) -> dict:
    t_start = time.perf_counter()
    sp = visa.load(cat)
    build = sp.build(k_build)
    print(f"[{cat}] build {len(build)}  stress {len(sp.stress)}  cal {len(sp.calibration)}  test {len(sp.test)}",
          flush=True)
    station = Station(backbones, cfg).build(build, sp.calibration, sp.stress,
                                            log=lambda m: print(f"[{cat}]{m}", flush=True))
    cal = station.calibration

    labels = sp.test_labels.astype(bool)
    good, bad = ~labels, labels
    t0 = time.perf_counter()
    test_imgs = np.asarray(sp.test)
    out = station.run(test_imgs, maps=True, active=("A", "B"))
    test_s = time.perf_counter() - t0
    s = station.combined(out, station.active)
    s_ab = station.combined(out, ("A", "B"))
    maps = np.max(np.stack([station.map_norm[k](out.raw_maps[k]) for k in station.active]), 0)
    dec = cal.decide(s)
    masks = np.asarray(sp.test_masks)

    fr_k, miss_k = int((dec[good] == "reject").sum()), int((dec[bad] == "pass").sum())
    n_good, n_bad = int(good.sum()), int(bad.sum())

    # ---- baselines at the same guaranteed false-reject target --------------------------------
    gt = GoldenTemplate().fit(list(build))
    gt_cal, gt_test = gt.score(list(sp.calibration)).scores, gt.score(list(test_imgs)).scores
    base = []
    for name, cs, ts in [("Golden-template difference", gt_cal, gt_test),
                         ("PatchCore, default threshold", station.norm["B"](station.dets["B"].score(
                             list(sp.calibration)).scores), out.z["B"]),
                         ("GoodPart, single threshold", station.cal_scores, s)]:
        t = st.conformal_threshold(cs, cal.alpha_guaranteed)
        fk, mk = int((ts[good] > t).sum()), int((ts[bad] <= t).sum())
        base.append({"category": cat, "k_build": len(build), "method": name, "auroc": auroc(labels, ts),
                     "false_reject_rate": fk / n_good, "false_reject_upper95": st.cp_upper(fk, n_good),
                     "miss_rate": mk / n_bad, "miss_upper95": st.cp_upper(mk, n_bad), "review_share": 0.0})
    base.append({"category": cat, "k_build": len(build), "method": "GoodPart (pass / review / reject)",
                 "auroc": auroc(labels, s), "false_reject_rate": fr_k / n_good,
                 "false_reject_upper95": st.cp_upper(fr_k, n_good), "miss_rate": miss_k / n_bad,
                 "miss_upper95": st.cp_upper(miss_k, n_bad), "review_share": float((dec == "review").mean())})

    # ---- POD: synthetic (stress pool) and real (VisA masks), on the same pass threshold -------
    meta = pd.DataFrame(station.defects_meta)
    meta["score"] = station.synth_scores
    meta["hit"] = meta["score"] >= cal.t_low
    scale = visa.SIZE / cfg.get("pod_reference_px", visa.SIZE)
    pods = {"synthetic": pod.fit(meta.size_px, meta.hit)}
    for c in cfg["stress_contrasts"]:
        sel = meta.contrast == c
        pods[f"synthetic_c{c}"] = pod.fit(meta.size_px[sel], meta.hit[sel])
    for kind in meta.kind.unique():
        sel = meta.kind == kind
        pods[f"synthetic_{kind}"] = pod.fit(meta.size_px[sel], meta.hit[sel])
    real_size = np.array([largest_region_diameter(m) for m in masks[bad]])
    real_hit = s[bad] >= cal.t_low
    pods["real"] = pod.fit(real_size, real_hit)
    sizes_grid = np.geomspace(2, 160, 48)
    agreement = []
    if "b0" in pods["synthetic"] and len(real_size):
        edges = np.unique(np.quantile(real_size, np.linspace(0, 1, 6)))
        for lo, hi in zip(edges[:-1], edges[1:]):
            sel = (real_size >= lo) & (real_size <= hi)
            if sel.any():
                agreement.append({"size_lo": float(lo), "size_hi": float(hi), "n": int(sel.sum()),
                                  "observed_real": float(real_hit[sel].mean()),
                                  "predicted_synthetic": float(np.mean(pod.curve(pods["synthetic"],
                                                                                 np.maximum(real_size[sel], 1))["pod"]))})

    row = {
        "category": cat, "k_build": len(build), "n_cal": cal.n_cal, "n_test_good": n_good, "n_test_bad": n_bad,
        "station": station.choice, **{f"synthetic_auroc_{k}": v for k, v in station.selection.items()},
        "auroc_A": auroc(labels, out.z["A"]), "auroc_B": auroc(labels, out.z["B"]), "auroc_AB": auroc(labels, s_ab),
        "auroc": auroc(labels, s), "auroc_ci": bootstrap_ci(labels, s),
        "pixel_auroc": pixel_auroc(masks, maps),
        "aupro_A": aupro(masks, out.raw_maps["A"]), "aupro_B": aupro(masks, out.raw_maps["B"]),
        "aupro": aupro(masks, maps),
        "alpha_target": cal.alpha_target, "alpha_guaranteed": cal.alpha_guaranteed,
        "t_low": cal.t_low, "t_high": cal.t_high, "review_certified": cal.review_certified,
        "false_reject_k": fr_k, "false_reject_rate": fr_k / n_good, "false_reject_upper95": st.cp_upper(fr_k, n_good),
        "miss_k": miss_k, "miss_rate": miss_k / n_bad, "miss_upper95": st.cp_upper(miss_k, n_bad),
        "defects_not_rejected": float((dec[bad] != "reject").mean()),
        "review_share": float((dec == "review").mean()), "review_share_good": float((dec[good] == "review").mean()),
        "a90_px": pods["synthetic"].get("a90"), "a90_95_px": pods["synthetic"].get("a90_95"),
        "a90_real_px": pods["real"].get("a90"), "a90_95_real_px": pods["real"].get("a90_95"),
        **{k: v for k, v in station.timings.items()},
        "test_img_per_s": len(test_imgs) / test_s, "total_s": time.perf_counter() - t_start,
        "device": config.device_label(),
    }

    cdir = out_dir / f"{cat}_k{len(build)}"
    cdir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"file": sp.test_files, "label": np.where(labels, "anomaly", "good"), "score": s,
                  "z_A": out.z["A"], "z_B": out.z["B"], "decision": dec,
                  "defect_size_px": [largest_region_diameter(m) if l else 0.0 for m, l in zip(masks, labels)]}
                 ).to_csv(cdir / "per_image.csv", index=False)
    meta.to_csv(cdir / "synthetic.csv", index=False)
    (cdir / "summary.json").write_text(json.dumps({
        "row": row, "calibration": cal.to_dict(), "guarantee": cal.guarantee_text(),
        "pod": {k: {**v, "curve": pod.curve(v, sizes_grid)} for k, v in pods.items()},
        "pod_agreement": agreement,
        "scores": {"calibration": station.cal_scores.tolist(), "synthetic": station.synth_scores.tolist(),
                   "test_good": s[good].tolist(), "test_bad": s[bad].tolist()},
        "selection": station.selection, "timings": station.timings}, default=float, indent=1))
    np.save(cdir / "test_maps.npy", maps.astype(np.float16))
    if cfg.get("save_station"):
        station.save(config.STORE_DIR / "stations" / f"visa_{cat}_k{len(build)}.pkl")
    print(f"[{cat}] k={len(build)} AUROC A {row['auroc_A']:.3f} B {row['auroc_B']:.3f} A+B {row['auroc_AB']:.3f} "
          f"station[{station.choice}] {row['auroc']:.3f} AUPRO {row['aupro']:.3f} | FRR {row['false_reject_rate']:.3f} "
          f"(<= {cal.alpha_guaranteed:.3f}) miss {row['miss_rate']:.3f} review {row['review_share']:.3f} | "
          f"a90/95 {row['a90_95_px']} px | {row['total_s']:.0f}s", flush=True)
    del station
    torch.cuda.empty_cache() if torch.cuda.is_available() else None
    return {"row": row, "baselines": base}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="configs/eval_visa.yaml")
    ap.add_argument("--categories", nargs="*")
    a = ap.parse_args()
    cfg = yaml.safe_load(open(a.config))
    torch.manual_seed(cfg.get("seed", 0))
    backbones = make_backbones(cfg)
    out_dir = config.RESULTS_DIR / cfg["name"]
    out_dir.mkdir(parents=True, exist_ok=True)
    rows, base = [], []
    for cat in a.categories or cfg["categories"]:
        for k in cfg["k_build"]:
            r = evaluate(cat, cfg, backbones, out_dir, None if k == "all" else int(k))
            rows.append(r["row"])
            base += r["baselines"]
            pd.DataFrame(rows).to_csv(out_dir / "results.csv", index=False)
            pd.DataFrame(base).to_csv(out_dir / "baselines.csv", index=False)
    (out_dir / "config.yaml").write_text(yaml.safe_dump(cfg))


if __name__ == "__main__":
    main()
