"""Model 2: IndicF5 base (350.7M, no chant fine-tune), via the official HF remote code (ai4bharat/IndicF5).

The local EdgeSanskrit-TTS/models/IndicF5 folder only holds model.safetensors (no modeling code), so this loads
from the HF hub on the EC2 instance (needs internet + `pip install transformers`; the repo may be gated: `hf auth login`).
It gets raw Devanagari text (no Kannada routing / chant text fixes), padas rendered one at a time and stitched,
with the same reference clip as Vagdhenu. Not run yet. If AutoModel loading fails, see NOTES.md "open questions".
    PYTHONPATH=. python POC/model_poc/run_indicf5.py
"""
import argparse, sys, time
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
import soundfile as sf
import common as K

ap = argparse.ArgumentParser()
ap.add_argument("--repo", default="ai4bharat/IndicF5")
a = ap.parse_args()

import torch
from transformers import AutoModel
dev = K.device()
ref = K.reference_clip()
model = AutoModel.from_pretrained(a.repo, trust_remote_code=True).to(dev)
run = K.Run("indicf5", {"repo": a.repo, "device": dev, "ref_text": ref["ref_text"]})
for v in K.load_verses():
    if run.done(v["id"]):
        K.log("skip", v["id"]); continue
    t = time.time()
    parts = []
    for p in v["padas"]:
        with torch.inference_mode():
            parts.append(K.to_float(model(p, ref_audio_path=ref["wav"], ref_text=ref["ref_text"])))
    w = K.stitch(parts)
    sf.write(str(run.wav_path(v["id"])), w, K.SR)
    run.record(v["id"], time.time() - t, len(w) / K.SR, text_source=v["text_source"])
    K.log(v["id"], run.data["verses"][v["id"]])
