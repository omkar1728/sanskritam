"""POC: Bhagavad Gita 2.47 via EdgeSanskrit-TTS (IndicF5 + Vocos) on CPU.

Renders the verse at the default pace and a slower pace, then encodes MP3s.
Usage: uv run python make_poc.py
"""
import os
import subprocess
import sys
import time

import soundfile as sf
import torch
from vocos import Vocos

# vocos 0.1.0's from_pretrained only takes HF repo ids; the bundle passes a local dir.
_vocos_from_pretrained = Vocos.from_pretrained.__func__


def _vocos_local(cls, repo_id, revision=None):
    if not os.path.isdir(repo_id):
        return _vocos_from_pretrained(cls, repo_id, revision)
    model = cls.from_hparams(os.path.join(repo_id, "config.yaml"))
    model.load_state_dict(torch.load(os.path.join(repo_id, "pytorch_model.bin"), map_location="cpu"))
    return model.eval()


Vocos.from_pretrained = classmethod(_vocos_local)

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "EdgeSanskrit-TTS"))
from generate_sanskrit_v2 import SanskritChantEngine  # noqa: E402

VERSE = "कर्मण्येवाधिकारस्ते मा फलेषु कदाचन।\nमा कर्मफलहेतुर्भूर्मा ते सङ्गोऽस्त्वकर्मणि॥"

# name -> seconds per syllable (None = reference clip's own pace, 0.326 s)
VARIANTS = {"default": None, "slow": 0.50}

OUT = os.path.join(HERE, "outputs")
os.makedirs(OUT, exist_ok=True)

engine = SanskritChantEngine(device="cpu", nfe_step=12, speed=0.90)

for name, sps in VARIANTS.items():
    t0 = time.perf_counter()
    sr, audio = engine.synthesize(VERSE, meter="anushtubh", seed=60, sps=sps)
    wav = os.path.join(OUT, f"gita_2_47_{name}.wav")
    mp3 = wav[:-4] + ".mp3"
    sf.write(wav, audio, sr, subtype="PCM_16")
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", wav,
         "-af", "adelay=400,apad=pad_dur=0.3,loudnorm=I=-18:TP=-1.5:LRA=7",
         "-ar", "44100", "-ac", "1", "-codec:a", "libmp3lame", "-b:a", "192k", mp3],
        check=True,
    )
    print(f"== {name}: {len(audio)/sr:.2f}s audio in {time.perf_counter()-t0:.0f}s -> {mp3}")
