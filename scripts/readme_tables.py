"""Print the README results tables from results/*.csv, so no number is typed by hand.

    python scripts/readme_tables.py > results/README_tables.md
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parent.parent
RES = ROOT / "results"


def cp_upper(k, n):
    return 1.0 if k >= n else float(stats.beta.ppf(0.95, k + 1, n - k))


def pct(x, d=1):
    return "n/a" if pd.isna(x) else f"{100 * x:.{d}f}%"


def main(name="visa_full"):
    r = pd.read_csv(RES / name / "results.csv")
    b = pd.read_csv(RES / name / "baselines.csv")
    out = []
    for label, sel in [("Full station (every remaining good image)", r.k_build > 32), ("Few-shot station (32 good images)", r.k_build == 32)]:
        x = r[sel].sort_values("category")
        out.append(f"\n**{label}**\n")
        out.append("| Category | Good images | Detectors | AUROC (A / B / station) | AUPRO | Miss rate (95% upper) | False-reject rate (95% upper) | Review share | a90/95 (px at 768) |")
        out.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
        for _, t in x.iterrows():
            # Flag only exceedances beyond chance: binomial test of k false rejects in n good parts at alpha.
            p_exceed = stats.binom.sf(t.false_reject_k - 1, t.n_test_good, t.alpha_guaranteed)
            flag = " ⚠" if p_exceed < 0.05 else ""
            out.append(f"| {t.category} | {t.k_build} | {t.station} | {t.auroc_A:.3f} / {t.auroc_B:.3f} / **{t.auroc:.3f}** | {t.aupro:.3f} | "
                       f"{pct(t.miss_rate)} ({pct(t.miss_upper95)}) | {pct(t.false_reject_rate)}{flag} ({pct(t.false_reject_upper95)}) | "
                       f"{pct(t.review_share, 0)} | {t.a90_95_px:.0f} |")
        fr, ng, mk, nb = x.false_reject_k.sum(), x.n_test_good.sum(), x.miss_k.sum(), x.n_test_bad.sum()
        out.append(f"| **All 12** | | | {x.auroc_A.mean():.3f} / {x.auroc_B.mean():.3f} / **{x.auroc.mean():.3f}** | {x.aupro.mean():.3f} | "
                   f"{mk}/{nb} = {pct(mk / nb)} ({pct(cp_upper(mk, nb))}) | {fr}/{ng} = {pct(fr / ng)} ({pct(cp_upper(fr, ng))}) | "
                   f"{pct(x.review_share.mean(), 0)} | |")

    out.append("\n**Against the baselines (means over the 12 categories, full stations, same 1% false-reject target)**\n")
    full = r[r.k_build > 32][["category", "k_build"]]
    bb = b.merge(full, on=["category", "k_build"]).groupby("method")[["auroc", "false_reject_rate", "miss_rate", "review_share"]].mean()
    zs_path = RES / "zeroshot" / "zeroshot_vllm.csv"
    out.append("| Method | AUROC | Miss rate | False-reject rate | Review share |")
    out.append("| --- | --- | --- | --- | --- |")
    order = ["Golden-template difference", "PatchCore, default threshold", "GoodPart, single threshold", "GoodPart (pass / review / reject)"]
    for m in order[:2]:
        t = bb.loc[m]
        out.append(f"| {m} | {t.auroc:.3f} | {pct(t.miss_rate)} | {pct(t.false_reject_rate)} | n/a |")
    if zs_path.exists():
        z = pd.read_csv(zs_path)
        n = z.n.sum()
        out.append(f"| Zero-shot VLM ({z.model.iloc[0]}) | {(z.auroc * z.n).sum() / n:.3f} | {pct((z.miss_rate * z.n).sum() / n)} | "
                   f"{pct((z.false_reject_rate * z.n).sum() / n)} | n/a |")
    for m in order[2:]:
        t = bb.loc[m]
        rs = pct(t.review_share, 0) if t.review_share else "n/a"
        bold = "**" if "review" in m else ""
        out.append(f"| {bold}{m}{bold} | {t.auroc:.3f} | {bold}{pct(t.miss_rate)}{bold} | {pct(t.false_reject_rate)} | {rs} |")

    few = RES / name / "fewshot.csv"
    if few.exists():
        f = pd.read_csv(few)
        g = f.groupby("k_label", sort=False)[["A", "B", "AB"]].mean()
        out.append("\n**Few-shot curve (mean image AUROC over categories)**\n")
        out.append("| Good images | " + " | ".join(g.index.astype(str)) + " |")
        out.append("| --- |" + " --- |" * len(g))
        for col, lab in [("A", "Detector A (DINOv2 kNN)"), ("B", "Detector B (PatchCore)"), ("AB", "Combined")]:
            out.append(f"| {lab} | " + " | ".join(f"{v:.3f}" for v in g[col]) + " |")

    bench = RES / "benchmark.json"
    if bench.exists():
        bj = json.loads(bench.read_text())
        out.append(f"\n**Compute (category {bj['category']}, both detectors, ${bj['gpu_hour_usd']}/GPU-hour)**\n")
        out.append("| Device | Build (s) | Inspection, batch 32 (img/s) | Single part p95 (ms) | Stress-test scoring (img/s) | Cost per 1,000 inspections |")
        out.append("| --- | --- | --- | --- | --- | --- |")
        for t in bj["rows"]:
            cost = f"${t['usd_per_1000_inspections']:.4f}" if "usd_per_1000_inspections" in t else "n/a"
            out.append(f"| {t['device']} | {t['build_A_s'] + t['build_B_s']:.1f} | {t['img_per_s_bs32']:.1f} | "
                       f"{t['batch_latency_ms_bs1_p95']:.0f} | {t['stress_img_per_s']:.1f} | {cost} |")
    print("\n".join(out))


if __name__ == "__main__":
    main(*sys.argv[1:])
