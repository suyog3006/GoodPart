"""Vision-language helpers. The VLM names defects and serves as a zero-shot baseline; it never
decides pass / review / reject.

Backends, tried in order of VLM_MODE: `vllm` (Qwen2.5-VL on our MI300X via vLLM), `tokenfactory`
(models hosted by AMD Token Factory), `template` (no model, geometry-based text).
"""
from __future__ import annotations

import base64
import json
import time

import cv2
import numpy as np

from goodpart import config

LABELS = ["scratch", "crack", "chip", "stain", "contamination", "missing feature", "deformation", "other"]

NAME_PROMPT = (
    "You are inspecting a manufactured part. Image 1 is a close-up crop of a region flagged as unusual; "
    "image 2 is the same crop with an anomaly heatmap (red = most unusual). "
    f"Name the defect with exactly one label from {LABELS}. "
    'Reply with JSON only: {"label": "<label>", "description": "<one short sentence>"}'
)

ZERO_SHOT_PROMPT = (
    "You are a visual quality inspector for manufactured parts. Look carefully for any defect: scratch, "
    "crack, chip, stain, contamination, missing or deformed feature, or anything unusual. "
    'Reply with JSON only: {"defective": true or false, "confidence": <number 0 to 1>, '
    '"where": "<short location, or none>"}'
)


def data_url(rgb: np.ndarray, max_side: int = 768) -> str:
    h, w = rgb.shape[:2]
    if max(h, w) > max_side:
        s = max_side / max(h, w)
        rgb = cv2.resize(rgb, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", cv2.cvtColor(np.asarray(rgb), cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 92])
    return "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode()


def _backend(mode: str):
    from openai import OpenAI

    if mode == "vllm":
        return OpenAI(base_url=config.VLLM_BASE, api_key="EMPTY", timeout=120, max_retries=1), config.VLLM_MODEL, \
            "AMD MI300X (vLLM)"
    return OpenAI(base_url=config.AMD_API_BASE, api_key=config.AMD_API_KEY, timeout=120, max_retries=2), \
        config.TF_MODEL, "AMD Token Factory"


def parse_json(text: str) -> dict:
    text = (text or "").strip()
    a, b = text.find("{"), text.rfind("}")
    return json.loads(text[a : b + 1])


def ask(images, prompt: str, mode: str | None = None, max_tokens: int | None = None) -> tuple[dict, dict]:
    mode = mode or config.VLM_MODE
    # Token Factory's default model reasons before answering, so it needs room beyond the JSON itself.
    max_tokens = max_tokens or (300 if mode == "vllm" else 2000)
    client, model, device = _backend(mode)
    content = [{"type": "text", "text": prompt}] + [{"type": "image_url", "image_url": {"url": data_url(im)}}
                                                     for im in images]
    t0 = time.perf_counter()
    kw = {"response_format": {"type": "json_object"}} if mode != "vllm" else {}
    r = client.chat.completions.create(model=model, messages=[{"role": "user", "content": content}],
                                       temperature=0, max_tokens=max_tokens, **kw)
    meta = {"model": model, "device": device, "latency_s": round(time.perf_counter() - t0, 3)}
    if r.usage is not None:
        extra = getattr(r.usage, "model_extra", None) or {}
        meta["tokens"] = r.usage.total_tokens
        if "cost" in extra:
            meta["cost_usd"] = extra["cost"]
    return parse_json(r.choices[0].message.content), meta


def template(length_mm: float | None, elongation: float) -> dict:
    elongated = elongation >= 4
    size = f"{length_mm:.1f} mm " if length_mm else ""
    return {"label": "scratch" if elongated else "other",
            "description": f"{size}{'elongated' if elongated else 'compact'} unusual region."}


def name_defect(crop, overlay, length_mm=None, elongation=1.0) -> dict:
    """Name one flagged region. Falls back vllm -> tokenfactory -> template on any failure."""
    order = {"vllm": ["vllm", "tokenfactory"], "tokenfactory": ["tokenfactory"]}.get(config.VLM_MODE, [])
    errors = []
    for mode in order:
        if mode == "tokenfactory" and not config.AMD_API_KEY:
            continue
        try:
            out, meta = ask([crop, overlay], NAME_PROMPT, mode)
            label = str(out.get("label", "other")).lower().strip()
            return {"label": label if label in LABELS else "other",
                    "description": str(out.get("description", ""))[:200], "source": mode, **meta}
        except Exception as e:  # network, quota, malformed JSON
            errors.append(f"{mode}: {type(e).__name__}")
    return {**template(length_mm, elongation), "source": "template", "errors": errors}


def overlay(rgb, heat, lo: float, hi: float, alpha: float = 0.6) -> np.ndarray:
    """Heatmap on a fixed scale [lo, hi]. Opacity grows with the score, so ordinary areas stay clear
    and only unusual regions are coloured; images of one station are directly comparable."""
    h = np.clip((np.asarray(heat, np.float32) - lo) / max(hi - lo, 1e-6), 0, 1)
    h = cv2.resize(h, (rgb.shape[1], rgb.shape[0]), interpolation=cv2.INTER_LINEAR)
    cm = cv2.cvtColor(cv2.applyColorMap((h * 255).astype(np.uint8), cv2.COLORMAP_INFERNO), cv2.COLOR_BGR2RGB)
    a = (alpha * np.clip(h * 1.5, 0, 1))[..., None]
    return (a * cm + (1 - a) * np.asarray(rgb)).astype(np.uint8)
