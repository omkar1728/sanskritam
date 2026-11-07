"""Model 3: Indic Parler-TTS (~938M per a third-party listing), via parler_tts.

Style is set by a text DESCRIPTION, not a reference clip, so this model gets no meter control: slowness comes only
from the description wording. It was trained for clips up to ~30 s, so padas are rendered one at a time and stitched.
Not run yet. The description and speaker are UNVERIFIED guesses; check the model card for Sanskrit speakers.
    pip install git+https://github.com/huggingface/parler-tts.git
    PYTHONPATH=. python POC/model_poc/run_parler.py --desc "..."   # try several --desc values (tag = --tag)
"""
import argparse, sys, time
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
import soundfile as sf
import common as K

DEFAULT_DESC = ("A male speaker delivers a very slow, calm, devotional chant with a deep, resonant voice. "
                "The recording is very clear with no background noise, in a close-up setting.")
ap = argparse.ArgumentParser()
ap.add_argument("--repo", default="ai4bharat/indic-parler-tts")
ap.add_argument("--desc", default=DEFAULT_DESC)
ap.add_argument("--tag", default="parler", help="output folder name, so several descriptions can be compared")
ap.add_argument("--seed", type=int, default=50)
a = ap.parse_args()

import torch
from parler_tts import ParlerTTSForConditionalGeneration
from transformers import AutoTokenizer
dev = K.device()
model = ParlerTTSForConditionalGeneration.from_pretrained(a.repo).to(dev)
tok = AutoTokenizer.from_pretrained(a.repo)
dtok = AutoTokenizer.from_pretrained(model.config.text_encoder._name_or_path)
sr = model.config.sampling_rate
run = K.Run(a.tag, {"repo": a.repo, "device": dev, "description": a.desc, "seed": a.seed, "sampling_rate": sr})
d_ids = dtok(a.desc, return_tensors="pt").to(dev)
for v in K.load_verses():
    if run.done(v["id"]):
        K.log("skip", v["id"]); continue
    t = time.time()
    parts = []
    for p in v["padas"]:
        pi = tok(p, return_tensors="pt").to(dev)
        torch.manual_seed(a.seed)
        with torch.inference_mode():
            g = model.generate(input_ids=d_ids.input_ids, attention_mask=d_ids.attention_mask,
                               prompt_input_ids=pi.input_ids, prompt_attention_mask=pi.attention_mask)
        parts.append(K.to_float(g.cpu().numpy().squeeze()))
    w = K.stitch(parts, sr=sr)
    sf.write(str(run.wav_path(v["id"])), w, sr)
    run.record(v["id"], time.time() - t, len(w) / sr, text_source=v["text_source"], sampling_rate=sr)
    K.log(v["id"], run.data["verses"][v["id"]])
