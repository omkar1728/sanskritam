# Alignment + MP3 cost POC (P1)

Plan and decision rule: `pipeline/SPEC.md` section 12. Code written, **never executed**.

Files
- `run_alignment_cost.py`: times MMS_FA alignment (cpu 1 thread, cpu N threads, cuda), validate/failure rate, MP3 encode at 192/96 kbps, and K-process contention. Uses existing WAVs only; padas from `verses_used.json` (the exact text they were rendered from).
- `summarize.py`: JSON -> markdown table (`alignment_cost.md`).
- `results/` (created on run): raw JSON.

Needs the WAVs under `POC/model_poc/results_s3/` (pull from `s3://sloka-poc-audio-785703562757/results/` if missing) and ffmpeg.

Run (repo root)
- Dev box (6 GB RAM, one model process only): `PYTHONPATH=. uv run python POC/alignment_poc/run_alignment_cost.py --modes cpu1,cpu4`
- EC2 T4: `PYTHONPATH=. python POC/alignment_poc/run_alignment_cost.py --modes cpu1,cpu4,cuda --contention 1,2,3`
- Summary: `python POC/alignment_poc/summarize.py POC/alignment_poc/results/<run>.json > POC/alignment_poc/alignment_cost.md`

Known risks: `align(..., device="cuda")` may fail if the loaded audio stays on CPU (the error is recorded per verse, not fatal); the model cache in `backend/engine/align.py` ignores the device, so the script calls `unload()` between modes; the contention run needs ~1.5 GB RAM per process (refuses below that unless `--force`).
