"""Few-shot curve: image AUROC of each detector and their combination vs number of build images.

    python -m goodpart.eval.fewshot --config configs/eval_visa.yaml --ks 1 8 16 32 64 128 all

Build sets are nested prefixes of the build pool; calibration images (for normalisation) are fixed.
"""
from __future__ import annotations

import argparse

import numpy as np
import pandas as pd
import torch
import yaml

from goodpart import config
from goodpart.calibrate import stats as st
from goodpart.data import visa
from goodpart.eval.metrics import auroc
from goodpart.eval.run import make_backbones
from goodpart.models.detectors import PatchCore, PatchKNN


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="configs/eval_visa.yaml")
    ap.add_argument("--ks", nargs="*", default=["1", "8", "16", "32", "64", "128", "all"])
    ap.add_argument("--categories", nargs="*")
    a = ap.parse_args()
    cfg = yaml.safe_load(open(a.config))
    bb = make_backbones(cfg)
    out = config.RESULTS_DIR / cfg["name"]
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for cat in a.categories or cfg["categories"]:
        sp = visa.load(cat)
        test = np.asarray(sp.test)
        y = sp.test_labels.astype(bool)
        for k in a.ks:
            build = sp.build(None if k == "all" else int(k))
            dets = {"A": PatchKNN(bb["A"]).fit(list(build)),
                    "B": PatchCore(bb["B"], coreset_ratio=cfg["coreset_ratio"], max_bank=cfg.get("max_bank_B")).fit(list(build))}
            z = {}
            for name, d in dets.items():
                norm = st.Normaliser.fit(d.score(list(sp.calibration)).scores)
                z[name] = norm(d.score(list(test)).scores)
            r = {"category": cat, "k": len(build), "k_label": k, "A": auroc(y, z["A"]), "B": auroc(y, z["B"]),
                 "AB": auroc(y, np.maximum(z["A"], z["B"]))}
            rows.append(r)
            print(r, flush=True)
            del dets
            torch.cuda.empty_cache()
            pd.DataFrame(rows).to_csv(out / "fewshot.csv", index=False)


if __name__ == "__main__":
    main()
