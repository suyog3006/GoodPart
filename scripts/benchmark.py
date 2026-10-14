"""Reproduce the AMD timing table: station build, stress-test scoring, inspection throughput and
p95 latency, on the GPU and (optionally) the same code on CPU.

    python scripts/benchmark.py --category pcb1 --compare-cpu --gpu-hour-usd 1.99
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from goodpart import config  # noqa: E402
from goodpart.data import visa  # noqa: E402
from goodpart.models.backbones import DinoV2, WideResNet50  # noqa: E402
from goodpart.models.detectors import PatchCore, PatchKNN  # noqa: E402
from goodpart.stress import synth  # noqa: E402


def timed(fn, *a):
    if torch.cuda.is_available():
        torch.cuda.synchronize()
    t0 = time.perf_counter()
    r = fn(*a)
    if torch.cuda.is_available():
        torch.cuda.synchronize()
    return r, time.perf_counter() - t0


def bench(device: str, sp, k_build: int, n_test: int, n_synth: int, label: str) -> dict:
    a = PatchKNN(DinoV2("facebook/dinov2-base", 672, device))
    b = PatchCore(WideResNet50(320, device), max_bank=100000)
    build = sp.build(k_build)
    test = np.asarray(sp.test[:n_test])
    out = {"device": label, "k_build": len(build)}
    _, out["build_A_s"] = timed(a.fit, list(build))
    _, out["build_B_s"] = timed(b.fit, list(build))
    a.score(list(test[:4])), b.score(list(test[:4]))  # warm-up
    for bs in (1, 32):
        per_img, per_batch = [], []
        for i in range(0, len(test), bs):
            chunk = list(test[i : i + bs])
            _, ta = timed(a.score, chunk)
            _, tb = timed(b.score, chunk)
            per_batch.append(ta + tb)
            per_img.append((ta + tb) / len(chunk))
        out[f"img_per_s_bs{bs}"] = 1.0 / float(np.mean(per_img))
        out[f"batch_latency_ms_bs{bs}_p95"] = float(np.percentile(per_batch, 95) * 1000)
    defects = [d.image for d in synth.grid(list(sp.stress), [8, 16, 32], [0.25], max(1, n_synth // 9))]
    _, t = timed(lambda: (a.score(defects), b.score(defects)))
    out["stress_img_per_s"] = len(defects) / t
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--category", default="pcb1")
    ap.add_argument("--k-build", type=int, default=100)
    ap.add_argument("--n-test", type=int, default=128)
    ap.add_argument("--n-synth", type=int, default=270)
    ap.add_argument("--compare-cpu", action="store_true")
    ap.add_argument("--gpu-hour-usd", type=float, default=float(os.environ.get("GPU_HOUR_USD", 1.99)))
    a = ap.parse_args()
    sp = visa.load(a.category)
    rows = []
    if torch.cuda.is_available():
        r = bench("cuda", sp, a.k_build, a.n_test, a.n_synth, config.device_label())
        r["usd_per_1000_inspections"] = a.gpu_hour_usd / 3600 / r["img_per_s_bs32"] * 1000
        rows.append(r)
        print(json.dumps(r), flush=True)
    if a.compare_cpu:
        torch.set_num_threads(os.cpu_count())
        r = bench("cpu", sp, a.k_build, min(a.n_test, 16), 27, f"CPU ({os.cpu_count()} threads)")
        rows.append(r)
        print(json.dumps(r), flush=True)
    out = config.RESULTS_DIR / "benchmark.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"category": a.category, "gpu_hour_usd": a.gpu_hour_usd, "rows": rows}, indent=1))


if __name__ == "__main__":
    main()
