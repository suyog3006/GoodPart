"""Hit/miss probability-of-detection model (MIL-HDBK-1823A).

logit(POD(a)) = b0 + b1 * log(a). a90 is the size detected 90% of the time; a90/95 is the one-sided
95% upper confidence bound on a90, i.e. we are 95% confident that POD >= 0.9 from that size up.
"""
from __future__ import annotations

import numpy as np
import statsmodels.api as sm
from scipy import stats

Z95 = float(stats.norm.ppf(0.95))
LOGIT90 = float(np.log(9.0))


def fit(sizes, hits) -> dict:
    a = np.asarray(sizes, float)
    y = np.asarray(hits, float)
    keep = a > 0
    a, y = a[keep], y[keep]
    out = {"n": int(len(y)), "hit_rate": float(y.mean()) if len(y) else None, "ok": False}
    if len(y) < 10 or y.min() == y.max():
        out["reason"] = "too few points or no variation"
        return out
    try:
        res = sm.Logit(y, sm.add_constant(np.log(a))).fit(disp=0)
    except Exception as e:  # perfect separation
        out["reason"] = type(e).__name__
        return out
    b0, b1 = map(float, res.params)
    cov = np.asarray(res.cov_params())
    out.update(b0=b0, b1=b1, cov=cov.tolist())
    if b1 <= 0:
        out["reason"] = "POD does not increase with size"
        return out
    log_a90 = (LOGIT90 - b0) / b1
    g = np.array([-1 / b1, -(LOGIT90 - b0) / b1**2])
    se = float(np.sqrt(g @ cov @ g))
    out.update(ok=True, a90=float(np.exp(log_a90)), a90_95=float(np.exp(log_a90 + Z95 * se)))
    return out


def curve(f: dict, sizes) -> dict:
    a = np.asarray(sizes, float)
    if "b0" not in f:
        return {"size": a.tolist(), "pod": [], "lower95": []}
    x = np.stack([np.ones_like(a), np.log(a)], 1)
    eta = x @ np.array([f["b0"], f["b1"]])
    se = np.sqrt(np.einsum("ij,jk,ik->i", x, np.asarray(f["cov"]), x))
    sig = lambda v: 1 / (1 + np.exp(-v))
    return {"size": a.tolist(), "pod": sig(eta).tolist(), "lower95": sig(eta - Z95 * se).tolist()}
