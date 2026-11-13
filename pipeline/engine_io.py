"""Glue between pipeline jobs and backend.engine (render spec, MP3 encode, alignment with retries, fake engine).

backend.engine.* is imported lazily inside functions; importing this module never loads torch.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FAKE_WAV = ROOT / "POC" / "outputs" / "gita_2_47_default.wav"
LEAD_MS = 400
TAIL_S = 0.3


def is_fake() -> bool:
    return os.environ.get("PIPELINE_FAKE") == "1"


# --------------------------------------------------------------------------- render spec
@dataclass
class FakeSpec:
    """Stand-in for synth.RenderSpec in fake mode (no bank / checkpoints needed)."""
    padas: list
    out_wav: str
    steps: int = 10
    seed: int = 50
    device: str = "cpu"
    meter: str = ""


_BANK_CACHE: list | None = None


def find_meter(name: str) -> dict:
    global _BANK_CACHE
    from backend.engine.meter import load_bank
    if _BANK_CACHE is None:
        _BANK_CACHE = load_bank()
    for m in _BANK_CACHE:
        if m["name"] == name:
            return m
    raise ValueError(f"unknown meter {name!r}; reference bank has: {', '.join(m['name'] for m in _BANK_CACHE)}")


def build_render_spec(job_params: dict, record, wav_path: str, device: str):
    """RenderSpec for one verse. Meter name -> bank clip (match on bank `name`)."""
    if is_fake():
        return FakeSpec(padas=list(record.padas), out_wav=str(wav_path), steps=int(job_params.get("steps", 10)),
                        seed=int(job_params.get("seed", 50)), device=device, meter=str(job_params.get("meter", "")))
    from backend.app import config as C
    from backend.engine.synth import RenderSpec
    m = find_meter(job_params["meter"])
    return RenderSpec(padas=list(record.padas), ref_wav=m["wav"], ref_text=m["ref_text"], sec_per_syll=m["sec_per_syll"],
                      voice_ckpt=str(C.MODELS / job_params["voice"]), vocoder_ckpt=str(C.MODELS / job_params["vocoder"]),
                      out_wav=str(wav_path), steps=int(job_params["steps"]), seed=int(job_params["seed"]),
                      speed=float(job_params["speed"]), cfg=float(job_params["cfg"]), gap=float(job_params["gap"]),
                      gap_halant=float(job_params["gap_halant"]), device=device)


# --------------------------------------------------------------------------- audio helpers
def wav_duration(wav: str) -> float:
    import soundfile as sf
    i = sf.info(str(wav))
    return i.frames / i.samplerate


def encode_mp3(wav: str, mp3: str, kbps: int = 192, lead_ms: int = LEAD_MS) -> None:
    """Same filter chain as backend.engine.mp3.wav_to_mp3 but with a configurable bitrate."""
    try:
        from backend.engine.mp3 import TAIL_S as tail
    except Exception:
        tail = TAIL_S
    if is_fake() and shutil.which("ffmpeg") is None:          # tests on boxes without ffmpeg
        Path(mp3).write_bytes(b"ID3FIXTURE-MP3" + Path(wav).read_bytes()[:2048])
        return
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav),
         "-af", f"adelay={lead_ms},apad=pad_dur={tail},loudnorm=I=-18:TP=-1.5:LRA=7",
         "-ar", "44100", "-ac", "1", "-b:a", f"{int(kbps)}k", str(mp3)], check=True)


# --------------------------------------------------------------------------- alignment
def fake_align(wav: str, padas: list[str], display_words=None, device: str = "cpu") -> dict:
    """Plausible alignment (two syllables per word, evenly spread). Fails for padas containing ALIGNFAIL when
    PIPELINE_FAKE_ALIGN_FAIL=1 (test hook)."""
    if os.environ.get("PIPELINE_FAKE_ALIGN_FAIL") == "1" and any("ALIGNFAIL" in p for p in padas):
        raise RuntimeError("injected alignment failure")
    dur = wav_duration(wav)
    words = [(li, w) for li, p in enumerate(padas) for w in p.split()]
    n = max(1, len(words))
    step = dur / n
    lines = [{"words": []} for _ in padas]
    for k, (li, w) in enumerate(words):
        a, b = k * step, (k + 1) * step
        mid = (a + b) / 2
        lines[li]["words"].append({
            "line": li, "slp1": w, "text": w, "start": round(a, 3), "end": round(b, 3),
            "syllables": [{"slp1": w[: max(1, len(w) // 2)], "start": round(a, 3), "end": round(mid, 3)},
                          {"slp1": w[max(1, len(w) // 2):] or w, "start": round(mid, 3), "end": round(b, 3)}]})
    return {"audio_duration": round(dur, 3), "lines": lines}


def default_aligner(device: str = "cpu"):
    if is_fake():
        return fake_align
    from backend.engine import align as A

    def _a(wav, padas, display_words=None):
        return A.align(wav, padas, display_words, device=device)
    return _a


def syllable_counts_or_none(padas: list[str]):
    if is_fake():
        return None
    try:
        from backend.engine.synth import syllable_counts
        return syllable_counts(padas)
    except Exception:
        return None


def align_with_retries(wav: str, padas: list[str], retries: int = 2, aligner=None, device: str = "cpu"):
    """Replicates backend.app.queue._align, retrying up to `retries` extra times.

    Returns (alignment_dict | None, last_error | None). The alignment is already shifted by LEAD_MS and carries
    `syllable_count_note` when only the syllable count differs from the text count. Also sets
    `align_with_retries.last_attempts` (attempts used) for metrics.
    """
    from backend.engine import align as A
    aligner = aligner or default_aligner(device)
    last_err = None
    attempts = 0
    for _ in range(1 + max(0, int(retries))):
        attempts += 1
        try:
            try:
                al = aligner(wav, padas, [p.split() for p in padas])
            except ValueError:                       # display-word mismatch: show SLP1 instead of Devanagari
                al = aligner(wav, padas)
            errs = A.validate(al, syllable_counts_or_none(padas))
            soft = [e for e in errs if "syllables, expected" in e]
            errs = [e for e in errs if e not in soft]
            if errs:
                last_err = "alignment rejected: " + "; ".join(errs[:5])
                continue
            if soft:
                al["syllable_count_note"] = "; ".join(soft)
            A.shift(al, LEAD_MS / 1000, al["audio_duration"] + LEAD_MS / 1000 + TAIL_S)
            align_with_retries.last_attempts = attempts
            return al, None
        except Exception as e:
            last_err = f"alignment unavailable: {e}"
    align_with_retries.last_attempts = attempts
    return None, (last_err or "alignment failed")[-500:]


align_with_retries.last_attempts = 0


def align_json_bytes(al: dict) -> bytes:
    return json.dumps(al, ensure_ascii=False).encode("utf-8")


# --------------------------------------------------------------------------- reading old blobs (reuse='wav')
def ref_off_len(ref) -> tuple[int, int]:
    """Blob reference as written by SegmentWriter: dict {off,len} (also offset/length) or [off, len]."""
    if isinstance(ref, dict):
        off = ref.get("off", ref.get("offset"))
        ln = ref.get("len", ref.get("length"))
        return int(off), int(ln)
    off, ln = ref
    return int(off), int(ln)


def pack_key(entry: dict, kind: str) -> str:
    """Store key of the pack holding `kind` (audio|align|wav) for a state entry."""
    from .segments import blob_path
    return blob_path(entry, kind)


def read_old_blob(store, entry: dict, kind: str) -> bytes:
    off, ln = ref_off_len(entry[kind])
    return store.read_range(pack_key(entry, kind), off, ln)


# --------------------------------------------------------------------------- fake engine
class FakeEngine:
    """Render = copy the POC wav. Padas containing RENDERFAIL raise (test hook). Used by tests/dry integration."""

    def __init__(self):
        self.delay = float(os.environ.get("PIPELINE_FAKE_DELAY", "0") or 0)

    def unload(self):
        pass

    def render(self, spec, progress=None) -> dict:
        if any("RENDERFAIL" in p for p in spec.padas):
            raise RuntimeError("injected render failure")
        if not FAKE_WAV.exists():
            raise FileNotFoundError(f"fake engine needs {FAKE_WAV}")
        if self.delay:
            time.sleep(self.delay)
        out = Path(spec.out_wav)
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(FAKE_WAV, out)
        return {"wav": str(out), "mels": [], "duration": wav_duration(str(out)), "pada_spans": [],
                "syllables": [max(1, len(p.replace(" ", ""))) for p in spec.padas]}


def make_engine():
    if is_fake():
        return FakeEngine()
    from backend.engine.synth import Engine
    return Engine()


def count_syllables(padas: list[str]) -> int:
    """Total syllables for ordering jobs (fake mode or failure: length of the text)."""
    if not is_fake():
        try:
            from backend.engine.synth import syllable_counts
            return int(sum(syllable_counts(padas)))
        except Exception:
            pass
    return sum(len(p.replace(" ", "")) for p in padas)
