"""Model 1: Vagdhenu (DiT 337M + BigVGAN 112M), the model the app uses today. Baseline for the comparison.

Uses the app's own engine (backend.engine.synth) so the result equals a normal app render. Needs EdgeSanskrit-TTS/
(vagdhenu + BigVGAN) next to the repo and the repo's python deps. Not run yet.
    PYTHONPATH=. python POC/model_poc/run_vagdhenu.py [--steps 16] [--seed 50]
"""
import argparse, sys, time
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
import common as K
from backend.app import config as C
from backend.engine.synth import Engine, RenderSpec

ap = argparse.ArgumentParser()
ap.add_argument("--steps", type=int, default=C.DEFAULT_STEPS)
ap.add_argument("--seed", type=int, default=C.DEFAULT_SEED)
ap.add_argument("--voice", default="voice_armA_ema_2026-06-11.pt", help="file in EdgeSanskrit-TTS/vagdhenu/models/")
ap.add_argument("--vocoder", default="voc_bigvgan_EMA_2026-06-11.pth")
a = ap.parse_args()

dev = K.device()
ref = K.reference_clip()
run = K.Run("vagdhenu", {"steps": a.steps, "seed": a.seed, "voice": a.voice, "vocoder": a.vocoder, "device": dev,
                         "ref_text": ref["ref_text"], "sec_per_syll": ref["sec_per_syll"]})
eng = Engine()
for v in K.load_verses():
    if run.done(v["id"]):
        K.log("skip", v["id"]); continue
    spec = RenderSpec(padas=v["padas"], ref_wav=ref["wav"], ref_text=ref["ref_text"], sec_per_syll=ref["sec_per_syll"],
                      voice_ckpt=str(C.MODELS / a.voice), vocoder_ckpt=str(C.MODELS / a.vocoder),
                      out_wav=str(run.wav_path(v["id"])), steps=a.steps, seed=a.seed, device=dev)
    t = time.time()
    res = eng.render(spec)
    run.record(v["id"], time.time() - t, res["duration"], syllables=res["syllables"], text_source=v["text_source"])
    K.log(v["id"], run.data["verses"][v["id"]])
