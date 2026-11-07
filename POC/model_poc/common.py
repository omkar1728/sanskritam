"""Shared helpers for the model POC (verse loading, reference clip, timing/RAM/GPU metrics, result files).

Nothing here loads a model. Run all scripts from the repo root so `backend.*` imports work:
    PYTHONPATH=. python POC/model_poc/run_vagdhenu.py
"""
from __future__ import annotations
import json, os, resource, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(os.environ.get("POC_OUT", ROOT / "POC" / "model_poc" / "outputs"))
SRC = ROOT / "test_data" / "ramayan" / "unified" / "baala" / "sarga_001"
N_VERSES = int(os.environ.get("POC_N", "10"))
SR = 24000
# first match wins; the chosen key is recorded in verses_used.json. Vulgate NET uses ङ् (not anusvara) before velars.
TEXT_PRIORITY = ("vulgate_net", "vulgate_in", "critical_smith")
GAP_S = 0.55          # pause between padas when a model renders one pada at a time (same as backend.engine.synth)


def load_verses(n: int = N_VERSES) -> list[dict]:
    """First `n` verses of Bala sarga 1 from test_data. Text comes from the files, never typed here."""
    out = []
    for i in range(1, n + 1):
        d = json.loads((SRC / f"verse_{i:03d}.json").read_text(encoding="utf-8"))
        for key in TEXT_PRIORITY:
            lines = (d.get("text", {}).get(key) or {}).get("lines")
            if lines:
                break
        else:
            raise ValueError(f"{d['id']}: none of {TEXT_PRIORITY} has lines")
        out.append({"id": d["id"], "text_source": key, "padas": [l.strip().rstrip("।॥|").strip() for l in lines]})
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "verses_used.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def reference_clip(name: str = "anuṣṭubh") -> dict:
    """Reference clip (wav + its text + sec_per_syll) from the Vagdhenu bank. Ramayana slokas are anushtubh.
    The SAME clip is used for every model that takes a reference, so the comparison is fair."""
    bank_json = ROOT / "EdgeSanskrit-TTS" / "vagdhenu" / "src" / "reference_bank" / "bank.json"
    e = json.loads(bank_json.read_text(encoding="utf-8"))[name]
    return {"wav": str(bank_json.parent / e["wav"]), "ref_text": e["ref_text"], "sec_per_syll": float(e["sec_per_syll"])}


def peak_rss_gb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024 / 1024      # Linux: KiB -> GiB


def gpu_peak_gb() -> float | None:
    try:
        import torch
        return torch.cuda.max_memory_allocated() / 1024 ** 3 if torch.cuda.is_available() else None
    except Exception:
        return None


def device() -> str:
    import torch
    return os.environ.get("POC_DEVICE") or ("cuda" if torch.cuda.is_available() else "cpu")


class Run:
    """Collects per-verse timings and writes outputs/<model>/results.json (resumable: finished verses are skipped)."""

    def __init__(self, model: str, params: dict | None = None):
        self.dir = OUT / model
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path = self.dir / "results.json"
        self.data = json.loads(self.path.read_text()) if self.path.exists() else {"model": model, "verses": {}}
        self.data["params"] = params or {}
        self.t_start = time.time()

    def wav_path(self, vid: str) -> Path:
        return self.dir / f"{vid}.wav"

    def done(self, vid: str) -> bool:
        return vid in self.data["verses"] and self.wav_path(vid).exists()

    def record(self, vid: str, wall_s: float, audio_s: float, **extra):
        self.data["verses"][vid] = {"wall_s": round(wall_s, 2), "audio_s": round(audio_s, 2),
                                    "rtf": round(wall_s / audio_s, 3) if audio_s else None,
                                    "peak_rss_gb": round(peak_rss_gb(), 2), "peak_gpu_gb": gpu_peak_gb(), **extra}
        self.save()

    def save(self):
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), encoding="utf-8")


def stitch(parts: list, gap_s: float = GAP_S, sr: int = SR):
    import numpy as np
    out = []
    for i, p in enumerate(parts):
        out.append(np.asarray(p, dtype=np.float32))
        if i < len(parts) - 1:
            out.append(np.zeros(int(gap_s * sr), np.float32))
    return np.concatenate(out)


def to_float(w):
    """int16 or float array -> float32 in [-1, 1]."""
    import numpy as np
    w = np.asarray(w)
    if w.dtype.kind in "iu":
        w = w.astype(np.float32) / 32768.0
    w = w.astype(np.float32)
    if np.abs(w).max() > 1.5:
        w = w / 32768.0
    return w


def log(*a):
    print(*a, flush=True)
