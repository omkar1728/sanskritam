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

## Known problem: MMS_FA weights cannot be downloaded (2026-11-12)

What happened
- Running the POC on the EC2 T4 box fails when `torchaudio.pipelines.MMS_FA` tries to fetch its checkpoint.
- URL (from `torchaudio/pipelines/_wav2vec2/impl.py`): `https://dl.fbaipublicfiles.com/mms/torchaudio/ctc_alignment_mling_uroman/model.pt`
- Cause: the TLS certificate of `dl.fbaipublicfiles.com` (Meta) expired on 2026-11-11. `curl` rejects it as well, so the problem is on Meta's side, not in our code or on the box.
- The checkpoint is not in the S3 setup copy (`s3://sloka-poc-audio-785703562757/setup/`): `bootstrap` and the setup bundle only ever held the Vāgdhenu files (gap in the plan, to be fixed).
- Certificate verification was NOT turned off, and must not be. The file is a pickled PyTorch checkpoint, so loading one fetched over an unverified connection could run arbitrary code.

Where a valid copy may still exist
- The owner ran alignment before on another machine, so the file is probably in that machine's torch cache: `~/.cache/torch/hub/checkpoints/model.pt` (or under `$TORCH_HOME/hub/checkpoints/`). The dev laptop checked on 2026-11-12 does not have it.

How to continue the POC
1. On the machine that has it, note the file size and `sha256sum` (record both below once known).
2. Copy it to the same path on the EC2 box with `scp`, e.g. `~/.cache/torch/hub/checkpoints/model.pt`. torch then finds it and skips the download. Do not use any HTTP/`verify=False` workaround.
3. Upload the file to `s3://sloka-poc-audio-785703562757/setup/torch_hub/model.pt` (private bucket) so the next box does not depend on Meta's server.
4. Rerun `run_alignment_cost.py` as described above.

Recorded checksum (fill in): `sha256 = ____________  size = ______ bytes`

Other options if no copy turns up: wait for Meta to renew the certificate (retry with verification on); or a third-party converted MMS forced-aligner (check the publisher and prefer safetensors/ONNX over a pickle; not evaluated). Torch >= 2.6 loads checkpoints with `weights_only=True` by default, which limits pickle risk, but only use a file from a source you trust.

Open code changes (not done yet)
- `run_alignment_cost.py` should skip a mode when the model fails to load, so the MP3-encode timings still run (they do not need the model). Today `run_mode` raises first.
- `pipeline/bootstrap.py` should stage the aligner checkpoint into `TORCH_HOME` from the S3 setup copy, and the S3 bundle should include it.
