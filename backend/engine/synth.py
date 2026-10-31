"""Library form of the validated CPU renderer (POC/render_cpu.py).

Default pipeline only: sandhi -> danda fix -> metathesis -> F5 DiT -> BigVGAN -> gate -> stitch.
Models are loaded once per process and kept warm; call `unload()` to free RAM.
"""
from __future__ import annotations
import json, os, sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import numpy as np
import soundfile as sf

from backend.app import config as C
from . import textprep as T

SR = 24000
_CFG = dict(dim=1024, depth=22, heads=16, ff_mult=2, text_dim=512, conv_layers=4)
_VIRAMA = "्್"


@dataclass
class RenderSpec:
    padas: list[str]                 # one text segment per pāda / half-verse
    ref_wav: str
    ref_text: str
    sec_per_syll: float
    voice_ckpt: str
    vocoder_ckpt: str
    out_wav: str
    steps: int = C.DEFAULT_STEPS
    seed: int = C.DEFAULT_SEED
    speed: float = 0.90
    cfg: float = 3.0
    gap: float = 0.55
    gap_halant: float = 0.20
    device: str = "cpu"


ProgressCb = Callable[[int, int, str], None]   # (done_padas, total_padas, message)


def _ends_halant(txt: str) -> bool:
    t = txt.rstrip(" ।॥|.,;:!?‌‍")
    return len(t) > 0 and t[-1] in _VIRAMA


def gate(au, voice=0.08, sil=0.012, fin=0.015, fout=0.040, lead=0.03, keep=0.06, fric=False):
    """Trim padding silence to tight speech bounds, with click-fades."""
    win = int(0.02 * SR)
    r = [float(np.sqrt((au[i:i + win] ** 2).mean())) for i in range(0, len(au) - win, win)]
    n = len(r)
    if n == 0:
        return au
    if fric:
        FR = 0.006
        s = next((i for i in range(n - 1) if r[i] > FR and r[i + 1] > FR), int(np.argmax(r)))
        while s > 0 and r[s - 1] > FR:
            s -= 1
        ve = max((i for i in range(n) if r[i] > 0.035), default=s)
    else:
        vs = next((i for i in range(n - 1) if r[i] > voice and r[i + 1] > sil), int(np.argmax(r)))
        s = vs
        while s > 0 and r[s - 1] > sil:
            s -= 1
        ve = max((i for i in range(n) if r[i] > 0.035), default=vs)
    start = max(0, s * win - int(lead * SR))
    end = min(len(au), ve * win + int(keep * SR))
    out = au[start:end].copy()
    fi, fo = (0 if fric else int(fin * SR)), int(fout * SR)
    if fi and len(out) > fi:
        out[:fi] *= np.linspace(0, 1, fi)
    if fo and len(out) > fo:
        out[-fo:] *= (np.cos(np.linspace(0, np.pi, fo)) * 0.5 + 0.5)
    return out


def prepare_pieces(padas: list[str]) -> list[str]:
    """Devanagari segments -> model text (Kannada-routed, sandhi and chant fixes applied)."""
    PT = _prep_text()
    pieces = [PT.model_text_sandhi(p, echo_final=False) for p in padas]
    pieces = [T._satva(x) for x in pieces]
    pieces = [T._danda_fix(T._anusvara_m(x)) for x in pieces]
    pieces = [T._hna_metathesis(x) for x in pieces]
    return [T._vocalic_l(x) for x in pieces]


def syllable_counts(padas: list[str]) -> list[int]:
    return [T.n_aksharas(x) for x in prepare_pieces(padas)]


def _prep_text():
    if str(C.SRC) not in sys.path:
        sys.path.insert(0, str(C.SRC))
    import prep_text as PT
    return PT


class Engine:
    """Holds the DiT + BigVGAN; reloads only if the checkpoint paths change."""

    def __init__(self):
        self._key = None
        self.cfm = self.cap = self.bigvgan = None

    def unload(self):
        self._key = self.cfm = self.cap = self.bigvgan = None
        import gc; gc.collect()

    def _load(self, spec: RenderSpec):
        key = (spec.voice_ckpt, spec.vocoder_ckpt, spec.device)
        if key == self._key:
            return
        import torch
        for p in (str(C.SRC), str(C.BIGVGAN_DIR)):
            if p not in sys.path:
                sys.path.insert(0, p)
        import bigvgan
        from f5_tts.infer.utils_infer import load_model, load_vocoder
        from f5_tts.model import DiT

        dev = spec.device
        cfm = load_model(DiT, _CFG, mel_spec_type="vocos", vocab_file=str(C.MODELS / "vocab.txt"), device=dev)
        ck = torch.load(spec.voice_ckpt, map_location="cpu", weights_only=True, mmap=True)
        ema = {k.replace("ema_model.", ""): v for k, v in ck["ema_model_state_dict"].items()
               if k not in ("initted", "step")}
        cfm.load_state_dict(ema, strict=False); cfm.eval(); del ck, ema

        class Cap:                      # captures the mel produced by the F5 pipeline
            def __init__(s, r): s.r, s.last = r, None
            def decode(s, m): s.last = m.detach().cpu().numpy(); return s.r.decode(m)

        cap = Cap(load_vocoder("vocos"))
        hp = bigvgan.load_hparams_from_json(str(C.BIGVGAN_DIR / "configs" / "bigvgan_v2_24khz_100band_256x.json"))
        g = bigvgan.BigVGAN(hp, use_cuda_kernel=False)
        bsd = torch.load(spec.vocoder_ckpt, map_location="cpu"); bsd = bsd.get("model", bsd)
        g.load_state_dict(bsd); g.remove_weight_norm(); g = g.eval().to(dev)
        for p in g.parameters():
            p.requires_grad = False
        self.cfm, self.cap, self.bigvgan, self._key = cfm, cap, g, key

    def _bvgan(self, mel, device):
        import torch
        m = torch.from_numpy(mel).to(device)
        with torch.no_grad():
            if m.dim() == 3 and m.shape[1] != 100 and m.shape[2] == 100:
                m = m.transpose(1, 2)
            return self.bigvgan(m).squeeze().cpu().numpy().astype(np.float32)

    def render(self, spec: RenderSpec, progress: Optional[ProgressCb] = None) -> dict:
        import torch, torchaudio
        from f5_tts.infer.utils_infer import infer_process, preprocess_ref_audio_text
        progress = progress or (lambda *a: None)
        progress(0, len(spec.padas), "loading models")
        self._load(spec)
        PT = _prep_text()

        pieces = prepare_pieces(spec.padas)
        nsyll = [T.n_aksharas(x) for x in pieces]
        fric_onset = PT.align_slp1(spec.padas[0])[:1] in ("S", "z", "s", "h")
        ref_audio, ref_t = preprocess_ref_audio_text(spec.ref_wav, spec.ref_text, clip_short=True)
        ra, rsr = torchaudio.load(ref_audio)
        ref_len = ra.shape[-1] / rsr

        out = Path(spec.out_wav); out.parent.mkdir(parents=True, exist_ok=True)
        segs, mel_paths = [], []
        for i, p in enumerate(pieces):
            progress(i, len(pieces), f"pada {i + 1}/{len(pieces)}")
            fixd = ref_len + nsyll[i] * spec.sec_per_syll if spec.sec_per_syll > 0 else None
            w = None
            for att in range(4):
                torch.manual_seed(spec.seed + att)
                w, _, _ = infer_process(ref_audio, ref_t, p, self.cfm, self.cap, mel_spec_type="vocos",
                                        speed=spec.speed, nfe_step=spec.steps, cfg_strength=spec.cfg,
                                        device=spec.device, fix_duration=fixd)
                w = np.array(w, dtype=np.float32)
                if np.abs(w).max() > 1.5:
                    w = w / 32768.0
                if float(np.sqrt((w ** 2).mean())) > 0.04:
                    break
            mp = f"{out}.mel{i}.npy"; np.save(mp, self.cap.last); mel_paths.append(mp)
            y = self._bvgan(self.cap.last, spec.device)
            mx = np.abs(y).max(); y = y / mx * 0.97 if mx > 1 else y
            segs.append(y)
            progress(i + 1, len(pieces), f"pada {i + 1}/{len(pieces)} done")

        gaps = [np.zeros(int(spec.gap * SR) + (int(spec.gap_halant * SR) if _ends_halant(p) else 0), np.float32)
                for p in pieces]
        parts, spans, t = [], [], 0.0
        for i, s in enumerate(segs):
            g = gate(s, fric=(fric_onset and i == 0))
            spans.append((t, t + len(g) / SR)); t += len(g) / SR
            parts.append(g)
            if i < len(segs) - 1:
                parts.append(gaps[i]); t += len(gaps[i]) / SR
        final = np.concatenate(parts)
        sf.write(str(out), final, SR)
        return {"wav": str(out), "mels": mel_paths, "duration": len(final) / SR,
                "pada_spans": spans, "syllables": nsyll}


def render_from_json(spec_path: str, progress: Optional[ProgressCb] = None) -> dict:
    spec = RenderSpec(**json.load(open(spec_path, encoding="utf-8")))
    return Engine().render(spec, progress)
