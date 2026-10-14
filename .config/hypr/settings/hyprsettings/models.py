"""Ollama helpers for the model pickers: what is installed, what each model can do, what suits this
GPU, and downloading a new one with progress."""

from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess
import threading
import urllib.error
import urllib.request
from typing import Callable

TIERS = {  # name: (chat, vision, download, needs)
    "full": ("gpt-oss:20b", "qwen2.5vl:7b", "~19 GB", "16 GB GPU memory"),
    "balanced": ("qwen3:8b", "qwen2.5vl:3b", "~8 GB", "8 GB GPU memory"),
    "light": ("qwen3:4b", "", "~3 GB", "4 GB GPU memory, or CPU only (slow)"),
}


def host() -> str:
    return os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")


def _request(path: str, payload: dict | None = None, timeout: float = 4):
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(host() + path, data=data, headers={"Content-Type": "application/json"},
                                 method="GET" if payload is None else "POST")
    return urllib.request.urlopen(req, timeout=timeout)


def installed() -> tuple[list[dict], str]:
    """([{name, size_gb}], error). The error is empty when Ollama answered."""
    try:
        with _request("/api/tags") as resp:
            tags = json.load(resp).get("models", [])
    except (urllib.error.URLError, OSError, ValueError) as e:
        return [], f"Ollama is not reachable at {host()} ({getattr(e, 'reason', e)}). Start it with: systemctl start ollama"
    return sorted(({"name": m.get("name", ""), "size_gb": round(m.get("size", 0) / 1e9, 1)} for m in tags),
                  key=lambda m: m["name"].lower()), ""


def capabilities(name: str) -> set[str]:
    """{'tools', 'vision', 'thinking', 'completion', ...} as reported by Ollama; empty when unknown."""
    try:
        with _request("/api/show", {"model": name}) as resp:
            return set(json.load(resp).get("capabilities") or [])
    except (urllib.error.URLError, OSError, ValueError):
        return set()


def vram_mib() -> int:
    best = 0
    if shutil.which("nvidia-smi"):
        try:
            out = subprocess.run(["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
                                 capture_output=True, text=True, timeout=5).stdout.split()
            best = max([int(x) for x in out if x.isdigit()] or [0])
        except (OSError, subprocess.SubprocessError):
            pass
    for path in glob.glob("/sys/class/drm/card*/device/mem_info_vram_total"):
        try:
            with open(path) as f:
                best = max(best, int(f.read().strip()) // 1048576)
        except (OSError, ValueError):
            pass
    return best


def recommend_tier(vram: int) -> str:
    return "full" if vram >= 14000 else "balanced" if vram >= 7000 else "light"


def pull(name: str, on_progress: Callable[[str, float | None], None], cancel: threading.Event) -> tuple[bool, str]:
    """Downloads a model. on_progress(status, fraction or None). Returns (ok, message)."""
    try:
        with _request("/api/pull", {"model": name, "stream": True}, timeout=60) as resp:
            for raw in resp:
                if cancel.is_set():
                    return False, "Cancelled"
                if not raw.strip():
                    continue
                item = json.loads(raw)
                if item.get("error"):
                    return False, str(item["error"])
                total, done = item.get("total"), item.get("completed")
                on_progress(item.get("status", ""), (done / total) if total and done is not None else None)
        return True, f"{name} is ready"
    except (urllib.error.URLError, OSError, ValueError) as e:
        return False, f"Download failed: {getattr(e, 'reason', e)}"
