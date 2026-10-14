"""Runtime settings from environment variables (and a local, git-ignored .env file)."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path = ROOT / ".env") -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


_load_dotenv()

DATA_DIR = Path(os.environ.get("GOODPART_DATA", Path.home() / "goodpart_data"))
STORE_DIR = Path(os.environ.get("GOODPART_STORE", DATA_DIR / "store"))
RESULTS_DIR = Path(os.environ.get("GOODPART_RESULTS", ROOT / "results"))

# Vision-language naming: self-hosted vLLM on the MI300X, or AMD Token Factory, or template text.
VLM_MODE = os.environ.get("VLM_MODE", "tokenfactory")  # vllm | tokenfactory | template
VLLM_BASE = os.environ.get("VLLM_BASE", "http://localhost:8001/v1")
VLLM_MODEL = os.environ.get("VLLM_MODEL", "Qwen/Qwen2.5-VL-7B-Instruct")
AMD_API_BASE = os.environ.get("AMD_API_BASE", "https://developer.amd.com.cn/radeon/api/v1")
AMD_API_KEY = os.environ.get("AMD_API_KEY", "")
TF_MODEL = os.environ.get("TF_MODEL", "Qwen3.8-27B")

API_TOKEN = os.environ.get("GOODPART_API_TOKEN", "")
ALLOWED_ORIGIN = os.environ.get("GOODPART_ALLOWED_ORIGIN", "http://localhost:3000")


def device() -> str:
    """PyTorch on ROCm exposes AMD GPUs as `cuda`, so the same string works on AMD and NVIDIA."""
    import torch

    return os.environ.get("DEVICE") or ("cuda" if torch.cuda.is_available() else "cpu")


def device_label() -> str:
    import torch

    if device().startswith("cuda") and torch.cuda.is_available():
        return torch.cuda.get_device_name(0)
    return "CPU"
