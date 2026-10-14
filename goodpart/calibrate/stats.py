"""Normalisation, conformal reject threshold, Learn-then-Test pass threshold, exact binomial bounds."""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import numpy as np
from scipy import stats


@dataclass
class Normaliser:
    """Robust z-score (score - median) / (1.4826 * MAD), fitted on calibration good parts."""

    median: float
    scale: float

    @classmethod
    def fit(cls, x) -> "Normaliser":
        x = np.asarray(x, np.float64)
        med = float(np.median(x))
        return cls(med, max(float(np.median(np.abs(x - med))) * 1.4826, 1e-8))

    def __call__(self, x):
        return (np.asarray(x) - self.median) / self.scale


def conformal_threshold(cal, alpha: float) -> float:
    """t = the ceil((n+1)(1-alpha))-th smallest calibration score.

    For a good part exchangeable with the calibration set, P(score > t) <= alpha.
    Returns +inf when n is too small to guarantee alpha (n < 1/alpha - 1).
    """
    s = np.sort(np.asarray(cal))
    r = math.ceil((len(s) + 1) * (1 - alpha))
    return float("inf") if r > len(s) else float(s[r - 1])


def achievable_alpha(n: int) -> float:
    return 1.0 / (n + 1)


def cp_upper(k: int, n: int, conf: float = 0.95) -> float:
    """One-sided exact Clopper-Pearson upper bound on a binomial rate."""
    if n == 0 or k >= n:
        return 1.0
    return float(stats.beta.ppf(conf, k + 1, n - k))


def cp_interval(k: int, n: int, conf: float = 0.95) -> tuple[float, float]:
    if n == 0:
        return 0.0, 1.0
    a = (1 - conf) / 2
    lo = 0.0 if k == 0 else float(stats.beta.ppf(a, k, n - k + 1))
    hi = 1.0 if k == n else float(stats.beta.ppf(1 - a, k + 1, n - k))
    return lo, hi


def learn_then_test(cal, t_high: float, review_cap: float, delta: float = 0.1, synth=None) -> dict:
    """Pass threshold t_low by Learn-then-Test (Angelopoulos, Bates et al.).

    Risk R(t) = share of good parts in the review band [t, t_high]. For each candidate t the null
    H_t: R(t) > review_cap has exact binomial p-value P(Bin(n, cap) <= k_t). Candidates are tested
    in fixed sequence from the highest t (least review) downward and testing stops at the first
    non-rejection, which controls the family-wise error at delta. Among the admissible t we pick
    the one with the fewest synthetic-defect misses, i.e. the lowest admissible t.
    """
    s = np.asarray(cal)
    n = len(s)
    top = t_high if np.isfinite(t_high) else float(s.max())
    cands = np.sort(np.unique(np.r_[s[s <= top], top]))[::-1]
    admissible = []
    for t in cands:
        k = int(((s >= t) & (s <= top)).sum())
        p = float(stats.binom.cdf(k, n, review_cap))
        if p > delta:
            break
        admissible.append((float(t), k, p))
    if not admissible:
        return {"t_low": float(top), "certified": False, "review_share_cal": 0.0, "n_admissible": 0}
    if synth is not None:
        ss = np.asarray(synth)
        t, k, p = min(admissible, key=lambda a: (float((ss < a[0]).mean()), -a[0]))
    else:
        t, k, p = admissible[-1]
    return {"t_low": t, "certified": True, "review_share_cal": k / n, "p_value": p,
            "n_admissible": len(admissible)}


@dataclass
class Calibration:
    alpha_target: float
    alpha_guaranteed: float
    review_cap: float
    delta: float
    t_low: float
    t_high: float
    n_cal: int
    review_certified: bool
    review_share_cal: float

    def to_dict(self):
        return asdict(self)

    def decide(self, score: np.ndarray) -> np.ndarray:
        score = np.asarray(score)
        return np.where(score > self.t_high, "reject", np.where(score < self.t_low, "pass", "review"))

    def guarantee_text(self) -> str:
        return (f"With {self.n_cal} calibration parts, the chance a good part is rejected is at most "
                f"{self.alpha_guaranteed:.1%} (while conditions match calibration).")


def calibrate(cal, alpha: float, review_cap: float, delta: float = 0.1, synth=None) -> Calibration:
    n = len(cal)
    a = max(alpha, achievable_alpha(n))
    t_high = conformal_threshold(cal, a)
    ltt = learn_then_test(cal, t_high, review_cap, delta, synth)
    return Calibration(alpha, a, review_cap, delta, ltt["t_low"], t_high, n, ltt["certified"],
                       ltt["review_share_cal"])
