# Vāgdhenu step-size POC

Status: **code written, NOTHING RUN** (syntax-checked only). Run on g4dn.xlarge (Tesla T4 16 GB, 4 vCPU, ~15 GB RAM).

## Goal
Vāgdhenu stays the default model. Find how the DiT `steps` setting trades time and resources: render the **same verse** at each step count and compare wall time, VRAM, RAM, GPU and CPU utilisation. The app default is 16 (`DEFAULT_STEPS`).

- Verse: Ramayana Bala kanda, sarga 1, verse 1 (`baala-001-001`, text from `test_data/`, `vulgate_net`). Identical text for every run.
- Steps: **16, 18, 20, 22, 24, 26, 28, 30, 32, 48, 64** (your list, sorted; 16 was listed once).
- Fixed: seed 50, voice `voice_armA_ema_2026-06-11.pt`, vocoder `voc_bigvgan_EMA_2026-06-11.pth`, `anuṣṭubh` reference clip, `speed`/`cfg`/gaps at engine defaults. Only `steps` changes.
- Method: one process, models loaded once, one discarded warm-up render, then 3 passes over all steps (steps interleaved per pass to spread clock/thermal drift). 33 timed renders, ~10 s each at low steps and ~40 s at 64, so about 10 minutes total.
- Metrics per render (sampled every 0.5 s on a background thread):
  | metric | source |
  |---|---|
  | wall time, RTF | `time.time()` around `Engine.render`, CUDA synchronised |
  | VRAM | `torch.cuda.max_memory_allocated` / `max_memory_reserved` (reset per render) and `nvidia-smi` used MiB peak |
  | RAM | sampled process RSS peak, plus `ru_maxrss` |
  | GPU util | `nvidia-smi` utilization.gpu, mean and max |
  | CPU | process CPU % (of one core, 400 max) and system CPU % (all cores) |
- Not measured: DiT vs BigVGAN time split (only DiT cost scales with steps; the vocoder part is fixed). The gap to a linear fit in the results hints at it.
- **USER-CHECK:** whether more steps sound better. Claude cannot hear audio. Listen to the wavs in S3 (names `step_SS_rR.wav`; repeat 1 is enough) and note where quality stops improving.

## Setup on the EC2 box (from `results.md`, 2026-11-08 run)
Bucket: `s3://sloka-poc-audio-785703562757` (private). The instance needs an IAM role with S3 get/put on it. **No Hugging Face token is needed**: Vāgdhenu weights come from S3 (they are public on HF `prathoshap/vagdhenu` anyway), and this POC does not touch the gated IndicF5/Parler repos.

1. **NVIDIA driver (stock image has none):**
   `sudo apt install -y nvidia-driver-580-server nvidia-utils-580-server`, then **reboot**; `nvidia-smi` must work afterwards.
2. **Scratch disk.** Root disk is ~8 GB (about 4 GB free), too small. The 116 GB instance-store NVMe is **ephemeral** (empty after stop/start). `ec2_env.sh` finds, formats and mounts it; use `/mnt/data` to match the earlier run:
   `export POC_NVME=/mnt/data POC_S3=s3://sloka-poc-audio-785703562757/results/vagdhenu-stepsize-<date>` then `source POC/model_poc/ec2_env.sh`.
   This puts the venv, caches, TMPDIR and outputs on the NVMe.
3. **Repo:** clone to `~/sanskritam` (use the branch/commit containing `POC/model_poc/run_vagdhenu_steps.py`).
4. **Weights and code** (not in git), from S3 into the NVMe, then symlink so `backend.app.config` finds them:
   ```
   aws s3 sync s3://sloka-poc-audio-785703562757/setup/EdgeSanskrit-TTS /mnt/data/EdgeSanskrit-TTS --only-show-errors   # 3.1 GB
   ln -sfn /mnt/data/EdgeSanskrit-TTS ~/sanskritam/EdgeSanskrit-TTS
   ```
   Do NOT sync `setup/hf/` (4.9 GB, only for IndicF5/Parler). `setup/restore.sh` is untested and also pulls `hf/`, so the steps above are done by hand.
5. **Python env:** Python 3.11, CUDA torch (the repo pins the CPU index; the earlier run used torch 2.8.0+cu126).
   ```
   aws s3 cp s3://sloka-poc-audio-785703562757/setup/requirements-lock.txt /mnt/data/
   cd ~/sanskritam && uv sync && uv pip install -r /mnt/data/requirements-lock.txt psutil
   uv run python -c "import torch; print(torch.__version__, torch.cuda.is_available())"   # must print True
   ```
   Check that the lock file leaves a CUDA torch. If not: `uv pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu126`. The lock file is the 206-package working set from the earlier run; `psutil` is added here in case it is missing.
6. **Run:** `source POC/model_poc/ec2_env.sh && bash POC/model_poc/run_steps.sh` (extra args pass through, e.g. `--repeats 5` or `--steps 16 32`).
   Nothing else should use the GPU (one model process at a time; a second process would distort the numbers).
7. **Collect:** wavs are uploaded by the script to `$POC_S3/audio/vagdhenu_steps/` (audio only, as requested). Everything else stays on the NVMe and is lost on stop: `scp` `/mnt/data/outputs/vagdhenu_steps/{summary.md,results.json,steps.csv}` and the log before stopping the instance.

## Files
- `run_vagdhenu_steps.py` benchmark, `summarize_steps.py` per-step table (mean over repeats), `run_steps.sh` runner plus audio upload.
- Uses `common.py` and `backend.engine.synth.Engine`, so a render equals an app render.

## Results
_No runs yet. Paste `outputs/vagdhenu_steps/summary.md` here._

## USER-CHECK
User listening result (2026-11-09): **no perceptible quality difference above 10 steps.** Steps 2-6 not recorded as acceptable. Wall time per verse on the T4: 7.1 s at 10 steps vs 10.5 s at the app default of 16 (about 32% less). `DEFAULT_STEPS` in `backend/app/config.py` is still 16.

| steps | pronunciation | pacing/meter | artefacts | verdict |
|---|---|---|---|---|

## Caveats
- One verse, one seed: the timing is solid, but audio quality differences between step counts may be seed-specific.
- Utilisation sampling at 0.5 s misses short spikes; GPU util is the `nvidia-smi` average over its last sample window.
- Process CPU % can exceed 100 (multi-thread); system CPU % is over all 4 vCPUs.
- Earlier runs saw ~11 s/verse at 16 steps after warm-up on this GPU, a useful sanity check for the 16-step row.
