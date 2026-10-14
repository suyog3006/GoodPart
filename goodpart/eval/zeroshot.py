"""Baseline: ask a vision-language model whether each VisA test image is defective.

    python -m goodpart.eval.zeroshot --mode vllm|tokenfactory [--categories ...] [--workers 16]

Score = confidence if "defective" else 1 - confidence. Results are cached per image, so a rerun
only queries images that failed or are new.
"""
from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd

from goodpart import config
from goodpart.calibrate import stats as st
from goodpart.data import visa
from goodpart.describe import vlm
from goodpart.eval.metrics import auroc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="vllm")
    ap.add_argument("--categories", nargs="*", default=visa.CATEGORIES)
    ap.add_argument("--workers", type=int, default=16)
    a = ap.parse_args()
    out = config.RESULTS_DIR / "zeroshot"
    out.mkdir(parents=True, exist_ok=True)
    cache_path = out / f"cache_{a.mode}.jsonl"
    cache = {}
    if cache_path.exists():
        for line in cache_path.read_text().splitlines():
            r = json.loads(line)
            cache[r["file"]] = r
    model = config.VLLM_MODEL if a.mode == "vllm" else config.TF_MODEL
    rows = []
    with open(cache_path, "a") as fh:
        for cat in a.categories:
            sp = visa.load(cat)
            todo = [i for i, f in enumerate(sp.test_files) if f not in cache or "error" in cache[f]]

            def query(i):
                f = sp.test_files[i]
                try:
                    ans, meta = vlm.ask([np.asarray(sp.test[i])], vlm.ZERO_SHOT_PROMPT, a.mode)
                    d = bool(ans.get("defective"))
                    c = float(ans.get("confidence", 0.5))
                    return {"file": f, "defective": d, "confidence": c, "score": c if d else 1 - c, **meta}
                except Exception as e:
                    return {"file": f, "error": f"{type(e).__name__}: {e}"[:200]}

            with ThreadPoolExecutor(a.workers) as ex:
                for r in ex.map(query, todo):
                    cache[r["file"]] = r
                    fh.write(json.dumps(r) + "\n")
                    fh.flush()
            res = [cache[f] for f in sp.test_files]
            ok = np.array(["error" not in r for r in res])
            y = sp.test_labels.astype(bool)[ok]
            score = np.array([r["score"] for r in res if "error" not in r])
            flag = np.array([r["defective"] for r in res if "error" not in r])
            fr_k, miss_k = int((flag & ~y).sum()), int((~flag & y).sum())
            lat = [r["latency_s"] for r in res if "latency_s" in r]
            row = {"category": cat, "mode": a.mode, "model": model, "n": int(ok.sum()), "errors": int((~ok).sum()),
                   "auroc": auroc(y, score), "false_reject_rate": fr_k / max(1, (~y).sum()),
                   "false_reject_upper95": st.cp_upper(fr_k, int((~y).sum())),
                   "miss_rate": miss_k / max(1, y.sum()), "miss_upper95": st.cp_upper(miss_k, int(y.sum())),
                   "median_latency_s": float(np.median(lat)) if lat else None,
                   "cost_usd": float(sum(r.get("cost_usd") or 0 for r in res))}
            rows.append(row)
            print(json.dumps(row), flush=True)
    pd.DataFrame(rows).to_csv(out / f"zeroshot_{a.mode}.csv", index=False)


if __name__ == "__main__":
    main()
