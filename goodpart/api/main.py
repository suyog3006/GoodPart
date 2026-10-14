"""GoodPart inference service (FastAPI). Runs on the AMD GPU machine.

    uvicorn goodpart.api.main:app --host 0.0.0.0 --port 8000

Every result records the device that produced it and its latency.
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
import queue
import sqlite3
import threading
import time
import uuid
from pathlib import Path

import cv2
import numpy as np
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from goodpart import config, pipeline
from goodpart.calibrate import stats as st
from goodpart.describe import vlm
from goodpart.drift import monitor
from goodpart.register import align
from goodpart.station import Station

STORE = config.STORE_DIR
# Shared showcase stations: anyone may inspect parts on them, but nobody can change their thresholds,
# zones or review labels through the API.
READONLY = {x.strip() for x in __import__("os").environ.get("GOODPART_READONLY_STATIONS", "").split(",") if x.strip()}
STATIONS_DIR = STORE / "stations"
IMG_DIR = STORE / "images"
DB_PATH = STORE / "goodpart.db"
DEFAULT_CFG = {
    "alpha": 0.01, "review_cap": 0.15, "delta": 0.1, "dino": "facebook/dinov2-base", "dino_size": 672,
    "wrn_size": 320, "coreset_ratio": 0.1, "max_bank_B": 100000, "map_size": 256, "select_margin": 0.01,
    "stress_sizes_px": [3, 4, 6, 8, 11, 16, 22, 32, 45, 64], "stress_contrasts": [0.1, 0.25, 0.5],
    "stress_per_cell": 4, "seed": 0, "mask_background": False,
}

app = FastAPI(title="GoodPart", version="0.1")
app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in config.ALLOWED_ORIGIN.split(",")],
                   allow_methods=["*"], allow_headers=["*"])

_lock = threading.Lock()
_backbones = None
_stations: dict[str, Station] = {}
_subscribers: list[queue.Queue] = []


# ---- infrastructure ---------------------------------------------------------------------------
def auth(authorization: str | None = Header(default=None)):
    if config.API_TOKEN and authorization != f"Bearer {config.API_TOKEN}":
        raise HTTPException(401, "invalid token")


def db() -> sqlite3.Connection:
    STORE.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.executescript("""
    CREATE TABLE IF NOT EXISTS station (id TEXT PRIMARY KEY, name TEXT, created REAL, status TEXT,
        mm_per_px REAL, zones TEXT DEFAULT '[]', meta TEXT DEFAULT '{}');
    CREATE TABLE IF NOT EXISTS image (id TEXT PRIMARY KEY, station TEXT, path TEXT, role TEXT, quality TEXT);
    CREATE TABLE IF NOT EXISTS inspection (id TEXT PRIMARY KEY, station TEXT, created REAL, score REAL,
        z TEXT, decision TEXT, band TEXT, reason TEXT, regions TEXT, device TEXT, latency_ms REAL,
        image_path TEXT, heatmap_path TEXT);
    CREATE TABLE IF NOT EXISTS review (inspection TEXT PRIMARY KEY, label TEXT, defect_type TEXT, created REAL);
    CREATE TABLE IF NOT EXISTS drift_event (id INTEGER PRIMARY KEY AUTOINCREMENT, station TEXT, created REAL,
        statistic REAL, p_value REAL, action TEXT);
    """)
    return con


def publish(event: str, data: dict):
    msg = f"event: {event}\ndata: {json.dumps(data, default=float)}\n\n"
    for q in list(_subscribers):
        q.put(msg)


_init_lock = threading.Lock()


def backbones():
    """Load the feature extractors once. Guarded: transformers' lazy imports are not thread-safe."""
    global _backbones
    with _init_lock:
        if _backbones is None:
            from goodpart.models.backbones import DinoV2, WideResNet50

            dev = config.device()
            _backbones = {"A": DinoV2(DEFAULT_CFG["dino"], DEFAULT_CFG["dino_size"], dev),
                          "B": WideResNet50(DEFAULT_CFG["wrn_size"], dev)}
    return _backbones


@app.on_event("startup")
def _warm():
    """Load models and the showcase stations' memory banks before the first visitor arrives."""
    backbones()
    for sid in READONLY:
        try:
            # One dummy inspection compiles the GPU kernels (~7 s on the first call, ~80 ms after).
            get_station(sid).run([np.zeros((768, 768, 3), np.uint8)], maps=True)
        except HTTPException:
            pass


def get_station(sid: str) -> Station:
    bb = backbones()
    with _init_lock:
        return _load_station(sid, bb)


def _load_station(sid: str, bb) -> Station:
    if sid not in _stations:
        p = STATIONS_DIR / f"{sid}.pkl"
        if not p.exists():
            raise HTTPException(404, "station not built")
        _stations[sid] = Station.load(p, bb, config.device())
    return _stations[sid]


def read_image(data: bytes) -> np.ndarray:
    arr = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if arr is None:
        raise HTTPException(400, "not an image")
    return cv2.cvtColor(arr, cv2.COLOR_BGR2RGB)


def png_b64(rgb: np.ndarray) -> str:
    ok, buf = cv2.imencode(".png", cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
    return base64.b64encode(buf.tobytes()).decode()


def station_row(con, sid):
    r = con.execute("SELECT * FROM station WHERE id=?", (sid,)).fetchone()
    if not r:
        raise HTTPException(404, "unknown station")
    return r


# ---- routes ---------------------------------------------------------------------------------
@app.get("/health")
def health():
    return {"ok": True, "device": config.device_label(), "vlm_mode": config.VLM_MODE}


@app.get("/events")
async def events():
    q: queue.Queue = queue.Queue()
    _subscribers.append(q)

    async def gen():
        try:
            yield "event: hello\ndata: {}\n\n"
            while True:
                try:
                    yield q.get_nowait()
                except queue.Empty:
                    await asyncio.sleep(0.2)
                    yield ": keep-alive\n\n"
        finally:
            _subscribers.remove(q)

    return StreamingResponse(gen(), media_type="text/event-stream")


class StationIn(BaseModel):
    name: str
    mm_per_px: float | None = None


@app.get("/stations", dependencies=[Depends(auth)])
def list_stations():
    con = db()
    out = []
    for r in con.execute("SELECT * FROM station ORDER BY created DESC"):
        d = dict(r)
        d["zones"], d["meta"] = json.loads(d["zones"]), json.loads(d["meta"])
        c = con.execute("SELECT decision, COUNT(*) n FROM inspection WHERE station=? GROUP BY decision", (r["id"],))
        d["counts"] = {x["decision"]: x["n"] for x in c}
        if d["status"] == "ready":
            d["meta"]["drift"] = monitor.status(r["id"]).get("status", "unknown")
        out.append(d)
    return out


@app.post("/stations", dependencies=[Depends(auth)])
def create_station(body: StationIn):
    sid = uuid.uuid4().hex[:10]
    con = db()
    con.execute("INSERT INTO station (id, name, created, status, mm_per_px) VALUES (?,?,?,?,?)",
                (sid, body.name, time.time(), "collecting", body.mm_per_px))
    con.commit()
    return {"id": sid}


@app.post("/stations/{sid}/images", dependencies=[Depends(auth)])
async def upload_good(sid: str, files: list[UploadFile] = File(...)):
    if sid in READONLY:
        raise HTTPException(403, "This showcase station is read-only. Set up your own station to change it.")
    con = db()
    station_row(con, sid)
    d = IMG_DIR / sid / "good"
    d.mkdir(parents=True, exist_ok=True)
    report = []
    for f in files:
        rgb = read_image(await f.read())
        q = align.quality(rgb)
        iid = uuid.uuid4().hex[:12]
        p = d / f"{iid}.png"
        cv2.imwrite(str(p), cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
        scale = align.detect_scale(rgb)
        if scale:  # store at the 768 px working resolution used everywhere downstream
            scale["mm_per_px"] *= rgb.shape[1] / 768
        q["scale"] = scale
        con.execute("INSERT INTO image VALUES (?,?,?,?,?)", (iid, sid, str(p), "good", json.dumps(q)))
        report.append({"id": iid, "file": f.filename, **q})
    con.commit()
    scales = [r["scale"]["mm_per_px"] for r in report if r.get("scale")]
    if scales:
        con.execute("UPDATE station SET mm_per_px=? WHERE id=?", (float(np.median(scales)), sid))
        con.commit()
    return {"uploaded": report}


def _build_job(sid: str, cfg: dict):
    con = db()
    try:
        rows = con.execute("SELECT * FROM image WHERE station=? AND role='good'", (sid,)).fetchall()
        rows = [r for r in rows if not json.loads(r["quality"])["flags"]]
        imgs = [cv2.cvtColor(cv2.imread(r["path"]), cv2.COLOR_BGR2RGB) for r in rows]
        size = 768
        imgs = [cv2.resize(im, (size, size), interpolation=cv2.INTER_AREA) for im in imgs]
        n = len(imgs)
        if n < 8:
            raise ValueError(f"need at least 8 usable good images, have {n}")
        rng = np.random.default_rng(0)
        order = rng.permutation(n)
        # Split: ~55% build, ~45% calibration. Synthetic defects are painted on copies of the held-out
        # calibration images: images already in the memory bank would match almost everywhere and make
        # defects look artificially easy to miss. Synthetic scores never enter the false-reject guarantee.
        n_cal = max(4, int(n * 0.45))
        cal = [imgs[i] for i in order[:n_cal]]
        build = [imgs[i] for i in order[n_cal:]]
        publish("build", {"station": sid, "stage": "features", "progress": 0.1})
        with _lock:
            s = Station(backbones(), cfg)
            s.build(build, cal, cal, log=lambda m: publish("build", {"station": sid, "stage": "log", "msg": m}))
            s.save(STATIONS_DIR / f"{sid}.pkl")
            _stations[sid] = s
        import pandas as pd
        from goodpart.stress import pod

        m = pd.DataFrame(s.defects_meta)
        m["hit"] = s.synth_scores >= s.calibration.t_low
        fit = pod.fit(m.size_px, m.hit)
        meta = {"n_build": len(build), "n_cal": len(cal), "timings": s.timings, "selection": s.selection,
                "a90_95_px": fit.get("a90_95"),
                "calibration": s.calibration.to_dict(), "device": config.device_label()}
        con.execute("UPDATE station SET status='ready', meta=? WHERE id=?", (json.dumps(meta, default=float), sid))
        con.commit()
        publish("build", {"station": sid, "stage": "done", "progress": 1.0, **meta})
    except Exception as e:
        con.execute("UPDATE station SET status='error', meta=? WHERE id=?", (json.dumps({"error": str(e)}), sid))
        con.commit()
        publish("build", {"station": sid, "stage": "error", "error": str(e)})


@app.post("/stations/{sid}/build", dependencies=[Depends(auth)])
def build(sid: str, alpha: float = 0.01, review_cap: float = 0.15):
    if sid in READONLY:
        raise HTTPException(403, "This showcase station is read-only. Set up your own station to change it.")
    con = db()
    station_row(con, sid)
    con.execute("UPDATE station SET status='building' WHERE id=?", (sid,))
    con.commit()
    threading.Thread(target=_build_job, args=(sid, {**DEFAULT_CFG, "alpha": alpha, "review_cap": review_cap}),
                     daemon=True).start()
    return {"status": "building"}


@app.get("/stations/{sid}", dependencies=[Depends(auth)])
def station_detail(sid: str):
    con = db()
    d = dict(station_row(con, sid))
    d["zones"], d["meta"] = json.loads(d["zones"]), json.loads(d["meta"])
    if (STATIONS_DIR / f"{sid}.pkl").exists():
        s = get_station(sid)
        from goodpart.stress import pod

        import pandas as pd

        m = pd.DataFrame(s.defects_meta)
        m["hit"] = s.synth_scores >= s.calibration.t_low
        f = pod.fit(m.size_px, m.hit)
        mm = d.get("mm_per_px")
        d["station"] = {"active": list(s.active), "selection": s.selection, "calibration": s.calibration.to_dict(),
                        "guarantee": s.calibration.guarantee_text(), "pod": {**f, "curve": pod.curve(
                            f, np.geomspace(2, 160, 48))}, "mm_per_px": mm,
                        "a90_95_mm": f.get("a90_95") * mm if f.get("a90_95") and mm else None,
                        "scores": {"calibration": s.cal_scores.tolist(), "synthetic": s.synth_scores.tolist()},
                        "timings": s.timings}
    return d


@app.get("/stations/{sid}/reference", dependencies=[Depends(auth)])
def reference_image(sid: str):
    """Reference photo for the zone editor: the sharpest, most typical good image."""
    con = db()
    rows = con.execute("SELECT path FROM image WHERE station=? AND role='good'", (sid,)).fetchall()
    if not rows:
        raise HTTPException(404, "no good images uploaded")
    imgs = [cv2.cvtColor(cv2.imread(r["path"]), cv2.COLOR_BGR2RGB) for r in rows[:60]]
    ref = cv2.resize(imgs[align.pick_reference(imgs)], (768, 768), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", cv2.cvtColor(ref, cv2.COLOR_RGB2BGR))
    return StreamingResponse(io.BytesIO(buf.tobytes()), media_type="image/jpeg")


class CalibIn(BaseModel):
    alpha: float
    review_cap: float
    delta: float = 0.1


@app.post("/stations/{sid}/calibrate", dependencies=[Depends(auth)])
def recalibrate(sid: str, body: CalibIn):
    """Live recalibration from stored calibration + synthetic scores (no GPU work)."""
    if sid in READONLY:
        raise HTTPException(403, "This showcase station is read-only. Set up your own station to change it.")
    s = get_station(sid)
    cal = st.calibrate(s.cal_scores, body.alpha, body.review_cap, body.delta, s.synth_scores)
    s.calibration = cal
    s.save(STATIONS_DIR / f"{sid}.pkl")
    expected_review = float(((s.cal_scores >= cal.t_low) & (s.cal_scores <= cal.t_high)).mean())
    synth_missed = float((s.synth_scores < cal.t_low).mean())
    return {"calibration": cal.to_dict(), "guarantee": cal.guarantee_text(),
            "expected_review_share": expected_review, "synthetic_miss_rate": synth_missed}


class ZonesIn(BaseModel):
    zones: list[dict]
    mm_per_px: float | None = None


@app.put("/stations/{sid}/zones", dependencies=[Depends(auth)])
def set_zones(sid: str, body: ZonesIn):
    if sid in READONLY:
        raise HTTPException(403, "This showcase station is read-only. Set up your own station to change it.")
    con = db()
    station_row(con, sid)
    con.execute("UPDATE station SET zones=? WHERE id=?", (json.dumps(body.zones), sid))
    if body.mm_per_px:
        con.execute("UPDATE station SET mm_per_px=? WHERE id=?", (body.mm_per_px, sid))
    con.commit()
    return {"ok": True}


def _name_regions(iid: str, rgb: np.ndarray, heat: np.ndarray, regions: list[dict], lo: float, vmax: float):
    out = []
    h, w = rgb.shape[:2]
    for r in regions:
        x, y, bw, bh = r["bbox"]
        pad = max(24, int(0.5 * max(bw, bh)))
        x0, y0, x1, y1 = max(0, x - pad), max(0, y - pad), min(w, x + bw + pad), min(h, y + bh + pad)
        crop = rgb[y0:y1, x0:x1]
        hm = cv2.resize(heat, (w, h))[y0:y1, x0:x1]
        r["name"] = vlm.name_defect(crop, vlm.overlay(crop, hm, lo, vmax), r.get("length_mm"), r["elongation"])
        out.append(r)
    con = db()
    con.execute("UPDATE inspection SET regions=? WHERE id=?", (json.dumps(out, default=float), iid))
    con.commit()
    publish("named", {"inspection": iid, "regions": out})


@app.post("/stations/{sid}/inspect", dependencies=[Depends(auth)])
async def inspect(sid: str, file: UploadFile = File(...), name_defects: bool = Form(True)):
    t0 = time.perf_counter()
    con = db()
    row = station_row(con, sid)
    s = get_station(sid)
    rgb = read_image(await file.read())
    size = 768
    img = cv2.resize(rgb, (size, size), interpolation=cv2.INTER_AREA)
    zones = json.loads(row["zones"])
    mm = row["mm_per_px"]  # mm per pixel at the 768 px working resolution
    with _lock:
        res = pipeline.decide(s, img, zones, mm)
    score, heat, decision, band, reason = res["score"], res["heat"], res["decision"], res["band"], res["reason"]
    regions = res["regions"]
    cal = s.calibration
    latency_ms = (time.perf_counter() - t0) * 1000
    iid = uuid.uuid4().hex[:12]
    d = IMG_DIR / sid / "inspections"
    d.mkdir(parents=True, exist_ok=True)
    ip, hp = d / f"{iid}.jpg", d / f"{iid}_heat.npy"
    cv2.imwrite(str(ip), cv2.cvtColor(img, cv2.COLOR_RGB2BGR))
    np.save(hp, heat.astype(np.float16))
    reg = [r.to_dict() for r in regions]
    rec = {"id": iid, "station": sid, "created": time.time(), "score": score,
           "z": res["z"], "decision": decision, "band": band, "reason": reason,
           "regions": reg, "device": config.device_label(), "latency_ms": latency_ms}
    con.execute("INSERT INTO inspection VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (iid, sid, rec["created"], score, json.dumps(rec["z"]), decision, band, reason,
                 json.dumps(reg, default=float), rec["device"], latency_ms, str(ip), str(hp)))
    con.commit()
    lo, vmax = s.region_threshold * 0.5, s.region_threshold * 2
    rec["image_png"] = png_b64(img)
    rec["overlay_png"] = png_b64(vlm.overlay(img, heat, lo, vmax))
    rec["heatmap_range"] = [lo, vmax]
    publish("inspection", {k: v for k, v in rec.items() if not k.endswith("_png")})
    monitor.observe(sid, score, decision, cal)
    if name_defects and reg:
        threading.Thread(target=_name_regions, args=(iid, img, heat, reg, lo, vmax), daemon=True).start()
    return rec


@app.get("/stations/{sid}/inspections", dependencies=[Depends(auth)])
def inspections(sid: str, decision: str | None = None, limit: int = 200):
    con = db()
    q = "SELECT i.*, r.label review_label, r.defect_type FROM inspection i LEFT JOIN review r ON r.inspection=i.id " \
        "WHERE station=?" + (" AND decision=?" if decision else "") + " ORDER BY created DESC LIMIT ?"
    args = (sid, decision, limit) if decision else (sid, limit)
    return [{**dict(r), "z": json.loads(r["z"]), "regions": json.loads(r["regions"])} for r in con.execute(q, args)]


@app.get("/inspections/{iid}/image", dependencies=[Depends(auth)])
def inspection_image(iid: str, overlay: bool = False):
    con = db()
    r = con.execute("SELECT * FROM inspection WHERE id=?", (iid,)).fetchone()
    if not r:
        raise HTTPException(404)
    img = cv2.cvtColor(cv2.imread(r["image_path"]), cv2.COLOR_BGR2RGB)
    if overlay:
        heat = np.load(r["heatmap_path"]).astype(np.float32)
        t = get_station(r["station"]).region_threshold
        img = vlm.overlay(img, heat, t * 0.5, t * 2)
    ok, buf = cv2.imencode(".jpg", cv2.cvtColor(img, cv2.COLOR_RGB2BGR))
    return StreamingResponse(io.BytesIO(buf.tobytes()), media_type="image/jpeg")


class ReviewIn(BaseModel):
    label: str  # good | defect
    defect_type: str | None = None


@app.post("/inspections/{iid}/review", dependencies=[Depends(auth)])
def review(iid: str, body: ReviewIn):
    """Inspector decision. Confirmed good parts join calibration; the guarantee tightens."""
    con = db()
    r = con.execute("SELECT * FROM inspection WHERE id=?", (iid,)).fetchone()
    if not r:
        raise HTTPException(404)
    if r["station"] in READONLY:
        raise HTTPException(403, "Review labels on this showcase station are not saved.")
    con.execute("INSERT OR REPLACE INTO review VALUES (?,?,?,?)", (iid, body.label, body.defect_type, time.time()))
    con.commit()
    out = {"ok": True}
    if body.label == "good":
        s = get_station(r["station"])
        s.cal_scores = np.r_[s.cal_scores, r["score"]]
        c = s.calibration
        s.calibration = st.calibrate(s.cal_scores, c.alpha_target, c.review_cap, c.delta, s.synth_scores)
        s.save(STATIONS_DIR / f"{r['station']}.pkl")
        out["calibration"] = s.calibration.to_dict()
        out["guarantee"] = s.calibration.guarantee_text()
    publish("review", {"inspection": iid, **body.model_dump()})
    return out


@app.get("/stations/{sid}/summary", dependencies=[Depends(auth)])
def summary(sid: str, hours: float = 12):
    con = db()
    since = time.time() - hours * 3600
    rows = con.execute("SELECT * FROM inspection WHERE station=? AND created>=? ORDER BY created", (sid, since)).fetchall()
    rev = {r["inspection"]: dict(r) for r in con.execute("SELECT * FROM review")}
    counts = {"pass": 0, "review": 0, "reject": 0}
    types, centroids = {}, []
    for r in rows:
        counts[r["decision"]] = counts.get(r["decision"], 0) + 1
        for g in json.loads(r["regions"]):
            name = (g.get("name") or {}).get("label", "unnamed")
            types[name] = types.get(name, 0) + 1
            x, y, w, h = g["bbox"]
            centroids.append([x + w / 2, y + h / 2])
        if r["id"] in rev and rev[r["id"]].get("defect_type"):
            t = rev[r["id"]]["defect_type"]
            types[t] = types.get(t, 0) + 1
    real_bad = [r for r in rows if rev.get(r["id"], {}).get("label") == "defect"]
    missed = sum(1 for r in real_bad if r["decision"] == "pass")
    return {"counts": counts, "n": len(rows), "defect_types": types, "centroids": centroids,
            "timeline": [{"t": r["created"], "decision": r["decision"], "score": r["score"]} for r in rows],
            "confirmed_defects": len(real_bad), "missed_confirmed": missed,
            "miss_upper95": st.cp_upper(missed, len(real_bad)) if real_bad else None,
            "drift": monitor.status(sid)}
