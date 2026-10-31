"""Slow a finished render by stretching its saved mel in time, then re-vocoding with BigVGAN.

Unlike a waveform time-stretch, the vocoder rebuilds clean phase for the slower timing.
Needs the <base>.wav.mel{i}.npy files written by render_cpu.py.
Usage: uv run python revocode.py outputs/exp/base_anushtubh_n16.wav 0.85 0.7
"""
import json
import os
import subprocess
import sys

import numpy as np
import soundfile as sf
import torch
import torch.nn.functional as F

HERE = os.path.dirname(os.path.abspath(__file__))
BIGVGAN = os.path.join(HERE, "EdgeSanskrit-TTS", "BigVGAN")
MODELS = os.path.join(HERE, "EdgeSanskrit-TTS", "vagdhenu", "models")
SR = 24000
GAP = 0.55

sys.path.insert(0, BIGVGAN)
import bigvgan  # noqa: E402

base, tempos = sys.argv[1], [float(t) for t in sys.argv[2:]]

g = bigvgan.BigVGAN(bigvgan.load_hparams_from_json(
    os.path.join(BIGVGAN, "configs", "bigvgan_v2_24khz_100band_256x.json")), use_cuda_kernel=False)
sd = torch.load(os.path.join(MODELS, "voc_bigvgan_EMA_2026-06-11.pth"), map_location="cpu")
g.load_state_dict(sd.get("model", sd))
g.remove_weight_norm()
g.eval()


def vocode(mel, tempo):
    m = torch.from_numpy(mel)
    if m.dim() == 3 and m.shape[1] != 100 and m.shape[2] == 100:
        m = m.transpose(1, 2)  # -> (1, 100, T)
    if tempo != 1.0:
        m = F.interpolate(m, scale_factor=1.0 / tempo, mode="linear", align_corners=False)
    with torch.no_grad():
        y = g(m).squeeze().numpy().astype(np.float32)
    mx = np.abs(y).max()
    return y / mx * 0.97 if mx > 1 else y


def gate(au, lead=0.03, keep=0.06):
    win = int(0.02 * SR)
    r = [float(np.sqrt((au[i:i + win] ** 2).mean())) for i in range(0, len(au) - win, win)]
    s = next((i for i, v in enumerate(r) if v > 0.012), 0)
    e = max((i for i, v in enumerate(r) if v > 0.035), default=len(r) - 1)
    out = au[max(0, s * win - int(lead * SR)):min(len(au), e * win + int(keep * SR))].copy()
    fi, fo = int(0.015 * SR), int(0.040 * SR)
    out[:fi] *= np.linspace(0, 1, fi)
    out[-fo:] *= np.cos(np.linspace(0, np.pi, fo)) * 0.5 + 0.5
    return out


mels = []
while os.path.exists(f"{base}.mel{len(mels)}.npy"):
    mels.append(np.load(f"{base}.mel{len(mels)}.npy"))
assert mels, f"no mel files next to {base}"

for t in tempos:
    segs = [gate(vocode(m, t)) for m in mels]
    parts = []
    for i, s in enumerate(segs):
        parts.append(s)
        if i < len(segs) - 1:
            parts.append(np.zeros(int(GAP / t * SR), dtype=np.float32))
    out = os.path.splitext(base)[0] + f"_mel{t:.2f}.wav"
    sf.write(out, np.concatenate(parts), SR)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", out,
                    "-af", "adelay=400,apad=pad_dur=0.3,loudnorm=I=-18:TP=-1.5:LRA=7",
                    "-ar", "44100", "-ac", "1", "-b:a", "192k", out[:-4] + ".mp3"], check=True)
    print(f"tempo {t}: {sum(map(len, parts)) / SR:.1f}s -> {out[:-4]}.mp3")
