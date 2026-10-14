"""Drift guard: compare recent scores with the calibration distribution (two-sample KS test).

The conformal guarantee only holds while new good parts look like the calibration parts. When the
recent score distribution shifts (moved camera, new lighting), the guarantee is paused.

Both samples are truncated at the reject threshold t_high: rejected parts are left out of the recent
window and calibration scores above t_high are left out of the reference. Truncating both at the same
point keeps the comparison fair while keeping clear defects from looking like drift. (Truncating at the
pass threshold instead would cut away most of the distribution and fire on healthy stations.)
"""
from __future__ import annotations

from collections import defaultdict, deque

import numpy as np
from scipy import stats

WINDOW = 50
MIN_N = 30
P_ALERT = 0.001

_recent: dict[str, deque] = defaultdict(lambda: deque(maxlen=WINDOW))
_cal: dict[str, np.ndarray] = {}
_t_high: dict[str, float] = {}
_state: dict[str, dict] = {}


def observe(station: str, score: float, decision: str, calibration) -> dict:
    if _t_high.get(station) != calibration.t_high:
        _cal.pop(station, None)
    _t_high[station] = calibration.t_high
    if score <= calibration.t_high:
        _recent[station].append(float(score))
    return status(station)


def set_reference(station: str, cal_scores, t_high: float = np.inf) -> None:
    c = np.asarray(cal_scores)
    _cal[station] = c[c <= t_high]


def test(recent, cal_scores) -> dict:
    r = np.asarray(recent)
    if len(r) < MIN_N:
        return {"status": "warming_up", "n": int(len(r))}
    ks = stats.ks_2samp(r, cal_scores)
    # Only an upward shift threatens the false-reject guarantee, but any strong shift is worth a look.
    shift = float(np.median(r) - np.median(cal_scores))
    drift = ks.pvalue < P_ALERT
    return {"status": "drift" if drift else "ok", "n": int(len(r)), "ks": float(ks.statistic),
            "p_value": float(ks.pvalue), "median_shift": shift,
            "action": "pause guarantee; re-register camera or recalibrate" if drift else None}


def status(station: str) -> dict:
    if station not in _cal:
        try:
            from goodpart.api.main import get_station

            s = get_station(station)
            set_reference(station, s.cal_scores, s.calibration.t_high)
        except Exception:
            return {"status": "unknown"}
    _state[station] = test(_recent[station], _cal[station])
    return _state[station]
