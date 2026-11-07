# Model POC: notes for Claude (pick up here)

**Status (2026-11-07): code written, NOTHING RUN.** Only a syntax parse (`ast.parse`) of the .py files was done. No model was loaded, no download, no audio. The plan is to run it on an EC2 instance later.

## Goal
Compare the top three TTS candidates on the first 10 verses of Ramayana Bala kanda, sarga 1 (`test_data/ramayan/unified/baala/sarga_001/verse_001..010.json`), to decide whether anything can replace or complement Vagdhenu in Sanskrit Śloka Studio. The use case needs slow, meter-aware chant; highlight sync depends on even syllable timing (see plan.md).

## The three models
| # | Script | Model | Params | Notes |
|---|---|---|---|---|
| 1 | `run_vagdhenu.py` | Vagdhenu DiT + BigVGAN (current app model) | 337.1M + 112.4M (counted from local checkpoints) | Baseline. Uses `backend.engine.synth.Engine`, so it equals an app render. Needs `EdgeSanskrit-TTS/` on the box. |
| 2 | `run_indicf5.py` | IndicF5 base, `ai4bharat/IndicF5` via HF `AutoModel(trust_remote_code)` | 350.7M (counted from local safetensors) | No chant fine-tune. Raw Devanagari text, per-pada render + stitch, same reference clip as #1. |
| 3 | `run_parler.py` | Indic Parler-TTS, `ai4bharat/indic-parler-tts` | ~938M (third-party listing, unverified); pretrained repo file 3.75 GB | Text-description style control, no reference clip, so no meter control. ~30 s clip limit, so per-pada + stitch. |

Fairness choices: same 10 verses, same text source (`vulgate_net` first, recorded per verse in `outputs/verses_used.json`), same reference clip (bank `anuṣṭubh`) for #1 and #2, same 0.55 s gap between padas.

## Files
- `common.py` verse loading, reference clip, metrics (wall, audio length, RTF, peak RAM, peak GPU), resumable `Run`, stitching.
- `run_vagdhenu.py`, `run_indicf5.py`, `run_parler.py` one per model. Each skips verses already in `outputs/<tag>/results.json`.
- `compare.py` writes `outputs/summary.md` (timings) and `outputs/listen.html` (side-by-side players). Loads no model.
- `run_all.sh` runs the three sequentially, then compare. `requirements-ec2.txt` extra pins (untested).
- `outputs/` is created at run time (gitignore it; wavs are large).

## How to run on EC2 (planned, untested)
1. Copy the repo plus `EdgeSanskrit-TTS/` (weights are gitignored), `uv sync` or equivalent, then `pip install -r POC/model_poc/requirements-ec2.txt`. Use a CUDA torch build on a GPU instance (the repo pins the CPU index; Colab T4 measured ~15 s/verse for Vagdhenu, ~3.6 GB RAM, ~2.2 GB GPU).
2. From the repo root: `bash POC/model_poc/run_all.sh`, or run one script with `PYTHONPATH=.`.
3. Copy `POC/model_poc/outputs/` back and open `listen.html`.
Run one model process at a time (RAM rule in CLAUDE.md applies on small instances too).

## Open questions / likely breakages (check first when it fails)
- **IndicF5 load:** the local folder has only `model.safetensors`. The script assumes the HF repo's remote code gives `model(text, ref_audio_path=, ref_text=)` returning a numpy array; the repo may be gated (`hf auth login`). If it fails, fall back to the repo's `f5_tts` DiT with the safetensors, as `synth.Engine._load` does for Vagdhenu (key names unchecked).
- **Parler:** the default description is a guess, speaker names for Sanskrit are unchecked, and no seed control beyond `torch.manual_seed`. Try several `--desc`/`--tag` values (e.g. slower, different pitch) before judging the model.
- Vagdhenu text goes through Kannada routing and chant text fixes in `backend/engine/textprep.py`; the other two get raw Devanagari, which is the honest "out of the box" test but may hurt them.
- No alignment in this POC. If a model sounds good, test it with `backend/engine/align.py` (MMS_FA) afterwards, since highlighting needs it.
- Verses may have 3+ lines; padas = lines, as in the app.

## USER-CHECK (Claude cannot hear audio)
Fill in after listening to `outputs/listen.html`:
| model | pronunciation | slow/steady chant pacing | meter feel | artefacts | verdict |
|---|---|---|---|---|---|
| vagdhenu | | | | | |
| indicf5 | | | | | |
| parler | | | | | |

## Results log (update after each run)
_No runs yet._

## Next steps
1. Run on EC2, fill the results log from `outputs/summary.md`.
2. User listens, fills the table above.
3. If an alternative is worth it: align its output, then design an executor/voice row (see `backend/executors/`, `voices` table) and record the decision in plan.md.
