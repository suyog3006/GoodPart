"""An inspection station: both detectors built from good images, normalised and calibrated.

Station selection and the pass threshold use only good images and synthetic defects; real defects
are never needed to set a station up.
"""
from __future__ import annotations

import pickle
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import torch

from goodpart.calibrate import stats as st
from goodpart.eval.metrics import auroc
from goodpart.models.detectors import PatchCore, PatchKNN, upsample
from goodpart.stress import synth

COMBOS = {"A": ("A",), "B": ("B",), "A+B": ("A", "B")}


@dataclass
class Output:
    raw: dict  # detector -> raw image scores
    z: dict  # detector -> normalised image scores
    score: np.ndarray  # combined score of the active detectors
    maps: np.ndarray | None  # combined normalised heatmaps (B, S, S)
    seconds: dict = field(default_factory=dict)


class Station:
    def __init__(self, backbones: dict, cfg: dict):
        self.cfg = cfg
        self.map_size = cfg.get("map_size", 256)
        self.dets = {
            "A": PatchKNN(backbones["A"], mask_background=cfg.get("mask_background", False),
                          max_bank=cfg.get("max_bank_A")),
            "B": PatchCore(backbones["B"], coreset_ratio=cfg.get("coreset_ratio", 0.1),
                           max_bank=cfg.get("max_bank_B")),
        }
        self.norm: dict[str, st.Normaliser] = {}
        self.map_norm: dict[str, st.Normaliser] = {}
        self.active = ("A", "B")
        self.selection: dict = {}
        self.calibration: st.Calibration | None = None
        self.timings: dict = {}

    # ---- scoring ------------------------------------------------------------------------------
    def run(self, images, maps: bool = True, active=None) -> Output:
        active = active or self.active
        raw, rmaps, secs = {}, {}, {}
        for k in active:
            r = self.dets[k].score(images)
            raw[k], secs[k] = r.scores, r.seconds
            if maps:
                rmaps[k] = upsample(r.maps, self.map_size)
        z = {k: self.norm[k](raw[k]) for k in raw} if self.norm else {}
        score = np.max(np.stack([z[k] for k in active]), 0) if z else None
        cmap = None
        if maps and self.map_norm:
            cmap = np.max(np.stack([self.map_norm[k](rmaps[k]) for k in active]), 0)
        out = Output(raw, z, score, cmap, secs)
        out.raw_maps = rmaps
        return out

    def combined(self, out: Output, combo) -> np.ndarray:
        return np.max(np.stack([out.z[k] for k in combo]), 0)

    # ---- building -----------------------------------------------------------------------------
    def build(self, build_imgs, cal_imgs, stress_imgs, log=print):
        cfg = self.cfg
        for k, d in self.dets.items():
            t0 = time.perf_counter()
            d.fit(build_imgs)
            torch.cuda.synchronize() if torch.cuda.is_available() else None
            self.timings[f"build_{k}_s"] = time.perf_counter() - t0
            log(f"  detector {k}: bank {tuple(d.bank.shape)} in {self.timings[f'build_{k}_s']:.1f}s")

        cal = self.run(cal_imgs, maps=True, active=("A", "B"))
        for k in ("A", "B"):
            self.norm[k] = st.Normaliser.fit(cal.raw[k])
            self.map_norm[k] = st.Normaliser.fit(cal.raw_maps[k][:, ::4, ::4].ravel())
        cal = Output(cal.raw, {k: self.norm[k](cal.raw[k]) for k in cal.raw}, None, None)

        # Synthetic stress set on held-out good images.
        t0 = time.perf_counter()
        defects = list(synth.grid(list(stress_imgs), cfg["stress_sizes_px"], cfg["stress_contrasts"],
                                  cfg["stress_per_cell"], seed=cfg.get("seed", 0)))
        self.timings["synth_generate_s"] = time.perf_counter() - t0
        t0 = time.perf_counter()
        syn = self.run([d.image for d in defects], maps=False, active=("A", "B"))
        self.timings["synth_score_s"] = time.perf_counter() - t0
        self.timings["n_synth"] = len(defects)
        good = self.run(stress_imgs, maps=False, active=("A", "B"))

        # Station selection on synthetic data only: keep A+B unless one detector is clearly better.
        for name, combo in COMBOS.items():
            s_good, s_syn = self.combined(good, combo), self.combined(syn, combo)
            self.selection[name] = auroc(np.r_[np.zeros(len(s_good)), np.ones(len(s_syn))], np.r_[s_good, s_syn])
        best = max(self.selection, key=self.selection.get)
        choice = "A+B" if self.selection["A+B"] >= self.selection[best] - cfg.get("select_margin", 0.01) else best
        self.active = COMBOS[choice]
        self.choice = choice
        log(f"  synthetic AUROC {({k: round(v, 4) for k, v in self.selection.items()})} -> {choice}")

        s_cal = self.combined(cal, self.active)
        s_syn = self.combined(syn, self.active)
        self.calibration = st.calibrate(s_cal, cfg["alpha"], cfg["review_cap"], cfg.get("delta", 0.1), s_syn)
        self.cal_scores, self.synth_scores = s_cal, s_syn
        self.defects_meta = [{"kind": d.kind, "size_px": d.size_px, "contrast": d.contrast} for d in defects]
        self._defects = defects  # kept in memory for galleries; not pickled
        return self

    def decide(self, score):
        return self.calibration.decide(score)

    # ---- persistence --------------------------------------------------------------------------
    def save(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        state = {"cfg": self.cfg, "norm": self.norm, "map_norm": self.map_norm, "active": self.active,
                 "selection": self.selection, "calibration": self.calibration, "timings": self.timings,
                 "cal_scores": self.cal_scores, "synth_scores": self.synth_scores,
                 "defects_meta": self.defects_meta, "choice": getattr(self, "choice", "A+B"),
                 "banks": {k: d.bank.cpu() for k, d in self.dets.items()},
                 "pca": {"pc": self.dets["A"].pc, "mean": self.dets["A"].pc_mean, "sign": self.dets["A"].pc_sign}}
        with open(path, "wb") as f:
            pickle.dump(state, f)

    @classmethod
    def load(cls, path: Path, backbones: dict, device: str = "cuda") -> "Station":
        with open(path, "rb") as f:
            s = pickle.load(f)
        st_ = cls(backbones, s["cfg"])
        for k in ("norm", "map_norm", "active", "selection", "calibration", "timings", "cal_scores",
                  "synth_scores", "defects_meta", "choice"):
            setattr(st_, k, s[k])
        for k, b in s["banks"].items():
            st_.dets[k].bank = b.to(device)
        a = st_.dets["A"]
        a.pc = None if s["pca"]["pc"] is None else s["pca"]["pc"].to(device)
        a.pc_mean = None if s["pca"]["mean"] is None else s["pca"]["mean"].to(device)
        a.pc_sign = s["pca"]["sign"]
        return st_
