"""Environment / device detection, worker sizing (SPEC 4.2, 4.3) and a small resource sampler.

Never imports torch at module level (and never imports it in the parent process at all).
"""
from __future__ import annotations

import importlib.util
import json
import math
import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

RENDER_VRAM_MB = 2600       # per render worker (2.34 GB allocated, 2.42 reserved on a T4)
RENDER_RAM_GB = 3.5         # per render worker
POST_RAM_GB = 1.5           # per post worker (MMS_FA ~1.2 GB)
IMDS = "http://169.254.169.254"


# --------------------------------------------------------------------------- environment
def imds_token(timeout: float = 1.0) -> str | None:
    """IMDSv2 session token, or None when not on EC2 (or unreachable)."""
    req = urllib.request.Request(f"{IMDS}/latest/api/token", method="PUT",
                                 headers={"X-aws-ec2-metadata-token-ttl-seconds": "60"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode()
    except Exception:
        return None


KAGGLE_DIR = Path("/kaggle/working")


def detect_env(environ: dict | None = None, probe=imds_token, kaggle_dir: Path | None = None) -> str:
    """'colab' | 'kaggle' | 'aws' | 'local'. PIPELINE_ENV overrides. kaggle_dir: overridable marker dir."""
    env = os.environ if environ is None else environ
    forced = (env.get("PIPELINE_ENV") or "").strip().lower()
    if forced in ("colab", "kaggle", "aws", "local"):
        return forced
    if env.get("COLAB_GPU") is not None or _importable("google.colab"):
        return "colab"
    if env.get("KAGGLE_KERNEL_RUN_TYPE") or env.get("KAGGLE_URL_BASE") or (kaggle_dir or KAGGLE_DIR).exists():
        return "kaggle"
    if env.get("AWS_EXECUTION_ENV") or probe(1.0):
        return "aws"
    return "local"


def _importable(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


# --------------------------------------------------------------------------- GPU
def _smi(fields: str) -> list[list[str]]:
    try:
        out = subprocess.check_output(["nvidia-smi", f"--query-gpu={fields}", "--format=csv,noheader,nounits"],
                                      text=True, timeout=5, stderr=subprocess.DEVNULL)
    except Exception:
        return []
    return [[c.strip() for c in line.split(",")] for line in out.splitlines() if line.strip()]


def gpu_info() -> list[dict]:
    """[{index, name, free_mb, total_mb}] via nvidia-smi ([] when no GPU)."""
    rows = []
    for r in _smi("index,name,memory.free,memory.total"):
        try:
            rows.append({"index": int(r[0]), "name": r[1], "free_mb": int(float(r[2])), "total_mb": int(float(r[3]))})
        except (ValueError, IndexError):
            continue
    return rows


def detect_device(requested: str | None = None) -> str:
    """'cuda' | 'cpu'. Explicit request, then PIPELINE_DEVICE, then autodetect (no torch import in this process)."""
    if requested and requested != "auto":
        return requested
    forced = (os.environ.get("PIPELINE_DEVICE") or "").strip().lower()
    if forced in ("cuda", "cpu"):
        return forced
    if os.environ.get("PIPELINE_FAKE") == "1":
        return "cpu"
    if "torch" in sys.modules or _importable("torch"):
        # a CPU-only torch build with a GPU box would render on cpu: ask a child process, never load torch here
        if not gpu_info():
            return "cpu"
        try:
            out = subprocess.check_output([sys.executable, "-I", "-c", "import torch;print(torch.cuda.is_available())"],
                                          text=True, timeout=120, stderr=subprocess.DEVNULL)
            return "cuda" if out.strip() == "True" else "cpu"
        except Exception:
            return "cpu"
    return "cuda" if gpu_info() else "cpu"


# --------------------------------------------------------------------------- /proc helpers
def meminfo_gb() -> tuple[float, float]:
    """(total, available) in GB from /proc/meminfo."""
    vals = {}
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            k, _, v = line.partition(":")
            vals[k] = int(v.split()[0])
    except Exception:
        return 0.0, 0.0
    return vals.get("MemTotal", 0) / 1048576, vals.get("MemAvailable", vals.get("MemFree", 0)) / 1048576


def free_ram_gb() -> float:
    return meminfo_gb()[1]


def cpu_cores() -> int:
    try:
        return len(os.sched_getaffinity(0))
    except Exception:
        return os.cpu_count() or 1


def _cpu_times() -> tuple[float, float]:
    try:
        f = Path("/proc/stat").read_text().splitlines()[0].split()[1:]
        v = [float(x) for x in f]
        return v[3] + (v[4] if len(v) > 4 else 0), sum(v)         # idle+iowait, total
    except Exception:
        return 0.0, 0.0


class Sampler(threading.Thread):
    """Samples system CPU %, RAM used and GPU util/mem (nvidia-smi) every `interval` seconds."""

    def __init__(self, interval: float = 0.5, gpu: bool = True):
        super().__init__(daemon=True, name="sampler")
        self.interval, self.gpu, self.rows = interval, gpu, []
        self._stop_evt = threading.Event()

    def stop(self):
        self._stop_evt.set()

    def run(self):
        idle0, tot0 = _cpu_times()
        while not self._stop_evt.wait(self.interval):
            idle1, tot1 = _cpu_times()
            dt = tot1 - tot0
            cpu = 100.0 * (1 - (idle1 - idle0) / dt) if dt > 0 else None
            idle0, tot0 = idle1, tot1
            total, avail = meminfo_gb()
            row = {"sys_cpu": cpu, "ram_used_gb": total - avail, "gpu_util": None, "gpu_mem_mib": None}
            if self.gpu:
                g = _smi("utilization.gpu,memory.used")
                if g:
                    try:
                        row["gpu_util"] = max(float(x[0]) for x in g)
                        row["gpu_mem_mib"] = max(float(x[1]) for x in g)
                    except ValueError:
                        pass
            self.rows.append(row)

    def summary(self) -> dict:
        def col(k): return [r[k] for r in self.rows if r[k] is not None]
        def mean(x): return round(sum(x) / len(x), 1) if x else None
        def mx(x): return round(max(x), 1) if x else None
        return {"samples": len(self.rows), "gpu_util_mean": mean(col("gpu_util")), "gpu_util_max": mx(col("gpu_util")),
                "gpu_mem_peak_mib": mx(col("gpu_mem_mib")), "sys_cpu_mean": mean(col("sys_cpu")),
                "sys_cpu_max": mx(col("sys_cpu")), "ram_used_peak_gb": round(max(col("ram_used_gb"), default=0), 2)}


# --------------------------------------------------------------------------- calibration (read only here; bench writes it)
def calib_path(gpu_name: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", gpu_name).strip("_") or "gpu"
    return Path.home() / ".cache" / "pipeline" / f"calib-{safe}.json"


def load_calib(gpu_name: str | None) -> dict | None:
    if not gpu_name:
        return None
    p = calib_path(gpu_name)
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) and int(d.get("best_workers", 0)) >= 1 else None
    except Exception:
        return None


# --------------------------------------------------------------------------- sizing
def _fit_ram(render_total: int, post: int, free_ram_gb: float) -> tuple[int, int]:
    """Shrink post workers (to 1) then render workers (to 1) until the set fits in RAM."""
    while render_total * RENDER_RAM_GB + post * POST_RAM_GB > free_ram_gb and post > 1:
        post -= 1
    while render_total * RENDER_RAM_GB + post * POST_RAM_GB > free_ram_gb and render_total > 1:
        render_total -= 1
    return render_total, post


def size_workers(device: str, free_vram_mb: float, free_ram_gb: float, cores: int, calib: dict | None = None,
                 n_gpus: int = 1, requested: int | None = None) -> dict:
    """SPEC 4.3. free_vram_mb is per GPU (the smallest one). `requested` overrides the render count per GPU.

    Returns {render_per_gpu, gpu_groups, render, post, notes}. render is the total render process count.
    """
    notes: list[str] = []
    cores = max(1, int(cores))
    if device == "cuda":
        groups = max(1, n_gpus)
        by_vram = int(free_vram_mb // RENDER_VRAM_MB)
        by_ram = int(free_ram_gb // RENDER_RAM_GB // groups) if groups else 0
        by_cores = max(1, (cores - 1) // groups)
        n = max(1, min(by_vram, by_ram, by_cores))
        if by_vram < 1:
            notes.append(f"only {free_vram_mb:.0f} MB free VRAM, a render worker needs ~{RENDER_VRAM_MB} MB")
        if calib and not requested:
            best = int(calib.get("best_workers", n))
            if best < n:
                notes.append(f"calibration: {best} worker(s) per GPU is within 5% of best throughput")
            n = max(1, min(n, best))
    else:
        groups = 1
        n = max(1, min(cores, int(free_ram_gb // RENDER_RAM_GB)))
    if requested:
        n = max(1, int(requested))
        if device == "cuda" and n * RENDER_VRAM_MB > free_vram_mb:
            notes.append(f"warning: {n} workers x {RENDER_VRAM_MB} MB may exceed {free_vram_mb:.0f} MB free VRAM")
    render_total = n * groups
    post = max(1, cores - render_total)
    fit_r, fit_p = _fit_ram(render_total, post, free_ram_gb)
    if (fit_r, fit_p) != (render_total, post):
        notes.append(f"reduced to {fit_r} render + {fit_p} post worker(s) to fit {free_ram_gb:.1f} GB free RAM")
        if requested:
            notes.append("warning: requested worker count would exceed RAM")
        render_total, post = fit_r, fit_p
        n = max(1, render_total // groups)
        if render_total < groups:
            groups = render_total
    need = render_total * RENDER_RAM_GB + post * POST_RAM_GB
    if need > free_ram_gb:
        notes.append(f"warning: minimum worker set needs ~{need:.1f} GB but only {free_ram_gb:.1f} GB RAM is free")
    return {"render_per_gpu": n, "gpu_groups": groups, "render": render_total, "post": post, "notes": notes}
