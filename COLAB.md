# Running renders on Google Colab (free T4)

**Status: this has NOT been run on real Colab by the author.** The notebook and these steps are written from the repo's code and pins only. The steps most likely to need adjustment:
1. The pip install cell (dependency resolution against Colab's preinstalled packages).
2. torch/torchaudio versions (the repo pins 2.8; Colab ships its own and the notebook does not reinstall torch).
3. rclone mount latency (the app may wait on Drive sync).

## Measured on a real Colab run (batch flow, T4)
Reported by the user from their first real run of `notebooks/colab_batch.ipynb` (not measured by Claude; 110-verse batch for Bala sarga 1, run 1):
- **Speed:** about 15 s per verse on average. Compare ~3.5 to 7 min per verse on the local CPU (plan.md section 3).
- **Memory:** about 3.6 GB system RAM and about 2.2 GB GPU RAM, so one T4 (16 GB) has headroom and the 12.7 GB Colab RAM is not the limit.
- **Setup:** the first run installs everything and takes about 10 minutes. Skip that on later runs in the same session by refreshing only `/content/app/backend` from Drive and rerunning the worker (see the snippet in the batch flow section).
- **Lesson, stale Drive code:** the notebook copies code from `sanskrit_studio/code/backend` on Drive. A copy uploaded before batch mode existed made the worker fail with `unrecognized arguments: --batch`. The notebook now prefers code shipped inside `batch.zip` (`code/backend`, overlaid on `/content/app/backend`, and it prints `code_version`); the Drive `code/` copy is only a fallback, used with a printed note when the zip has no `code/backend`. Re-sync Drive `code/backend` (rsync in setup step 1) only if you rely on that fallback.
- **Extrapolation, not measured:** at 15 s per verse a 110-verse sarga is about 28 min; all of Bala (2275 renderable verses) about 9.5 h; the whole Ramayana (26,100) about 109 h. Longer verses and the first-verse model load will change this. Alignment and MP3 run afterwards on the app machine (MMS_FA ~1.2 GB RAM), and their speed has not been measured.

## Batch flow (one cell, no Drive polling)
Use this to render many verses at once. Still NOT run on real Colab by the author (same caveats as above). One-time Drive setup (models + code in `sanskrit_studio/`, steps 1 and 2 below) is still needed.
1. In the app, create a batch and download `batch.zip`.
2. Open `notebooks/colab_batch.ipynb` in Colab (upload it or open from Drive).
3. Runtime > Change runtime type > T4 GPU.
4. Run the single code cell (set `DRIVE_FOLDER` if you named the folder differently). Allow the Drive prompt.
5. When asked, choose `batch.zip`. Wait; the output shows one line per job (`[batch] 3/20 job 41 ok 12.3s`) and PROGRESS lines.
6. Results are written straight to Drive (see layout below). The cell ends with an ok/failed summary, the Drive folders, and the next step. `results.zip` is built on Drive; it downloads to your computer only if the form field `DOWNLOAD_ZIP` is ticked (default off).
7. Get the results into the app, either way:
   - **Import from Drive folder:** Generate > Epic verses > your batch > Import from Drive folder (needs the Drive folder mounted locally, e.g. the rclone mount below).
   - **Upload zip:** download `results.zip` from Drive (`<DRIVE_FOLDER>/batch_results/_batches/<batch_id>/results.zip`, or tick `DOWNLOAD_ZIP`) and upload it in the app. Failed jobs are listed in `results/errors.json` inside it.

### Where results are (Drive layout)
The layout comes from `batch.json` (`results_root`, `batch_dir`, per-job `result_dir`); the notebook hardcodes no paths. Every path is validated (no absolute, `..`, backslash or drive letter) or the batch is rejected.
```
My Drive/sanskrit_studio/            (DRIVE_FOLDER)
  batch_results/
    ramayana/baala/sarga_001/
      baala-001-001/  chant.wav  result.json
      baala-001-002/  chant.wav  result.json
    _batches/<batch_id>/  errors.json  results.zip
```
`chant.wav` is written to a temporary name and renamed, and `result.json` is written last: a verse counts as done only when both files exist, so a dropped VM or Drive sync never leaves a half file counted as done.

### Parallel workers (`WORKERS`)
The form field `WORKERS` (default 1) starts that many worker processes, each with its own warm model; verse k goes to worker k % N. Output lines are prefixed `[w0]`, `[w1]`. Each process needs about 3.6 GB system RAM and 2.2 GB GPU RAM (measured). On a free Colab (2 vCPU, 12 GB RAM, T4 15 GB) use **2 at most**; 3 or more risks running out of RAM and crashing the runtime. The worker prints a WARNING (does not block) if N x 3.6 GB exceeds available RAM or N exceeds the CPU count. Workers start staggered (up to 20 s apart) to avoid a RAM spike while loading models. Failed verses from all workers are merged into `<batch_dir>/errors.json`.
**Speed-up with 2 workers is NOT yet measured.** The cell prints `n rendered, X s/verse incl. model load` (only verses rendered in this run, wall time of the worker run; `nothing new to render` if none); please run the same batch with `WORKERS = 1` and `WORKERS = 2` and compare.

### Resume
Run the cell again with the same `batch.zip`: verses whose `result.json` and `chant.wav` already exist on Drive are skipped by every worker, even after a VM wipe. If no verse has results, the cell prints the errors and stops before building the zip.

Batch troubleshooting:
- **Disconnect / session reset:** run the cell again and upload the same `batch.zip`. Finished jobs are read from the Drive `batch_results` folders and skipped, even after a VM wipe.
- **Out of memory with WORKERS > 1:** lower `WORKERS`, restart the session.
- **A job failed:** others still complete. Fix the cause (see the message in the summary) and make a new batch with just those verses.
- **No GPU:** the cell stops with a message; change runtime or retry later.
- **No download:** it is off by default; tick `DOWNLOAD_ZIP` and rerun (everything done is skipped), or fetch `results.zip` from Drive.

No tunnel is used. The app and the Colab worker exchange files through a shared Google Drive folder.

## One-time setup

### 1. Prepare the folder locally
Run from the repo root. Result is `~/sanskrit_studio_upload` (about 3 GB, mostly weights).

```bash
R=~/sanskrit_studio_upload
mkdir -p $R/models $R/code/vagdhenu $R/jobs
cp EdgeSanskrit-TTS/vagdhenu/models/{voice_steer_ema_2026-06-17.pt,voice_armA_ema_2026-06-11.pt,voc_bigvgan_EMA_2026-06-11.pth,vocab.txt} $R/models/
rsync -a --exclude '__pycache__' --exclude '.venv' --exclude 'storage' --exclude 'tests' --exclude 'outputs' backend/ $R/code/backend/
rsync -a --exclude '__pycache__' EdgeSanskrit-TTS/vagdhenu/src/ $R/code/vagdhenu/src/
rsync -a --exclude '__pycache__' --exclude '.git' EdgeSanskrit-TTS/BigVGAN/ $R/code/BigVGAN/
```

Expected layout:
```
sanskrit_studio/
  models/  voice_steer_ema_2026-06-17.pt  voice_armA_ema_2026-06-11.pt
           voc_bigvgan_EMA_2026-06-11.pth  vocab.txt
  code/    backend/  vagdhenu/src/  BigVGAN/
  jobs/    (created by the app)
```
Note `models/` is not inside `code/`; the notebook symlinks it. If `backend/storage` holds your DB, it is excluded on purpose.

### 2. Upload to Drive
Either drag `sanskrit_studio_upload` into My Drive and rename it `sanskrit_studio`, or with rclone (next step):
```bash
rclone copy ~/sanskrit_studio_upload gdrive:sanskrit_studio --progress
```

### 3. rclone on Linux (mount the Drive folder locally)
```bash
sudo apt install rclone fuse3      # or: curl https://rclone.org/install.sh | sudo bash
rclone config                      # n) new remote, name: gdrive, storage: drive,
                                   # scope: 1 (full access, "drive"), leave the rest default,
                                   # authorize in the browser
mkdir -p ~/gdrive_sanskrit
rclone mount gdrive:sanskrit_studio ~/gdrive_sanskrit --vfs-cache-mode full --dir-cache-time 10s --poll-interval 10s
```
Keep that terminal open (or run it as a service). Bisync is not needed. Check `ls ~/gdrive_sanskrit/models`.

### 4. App settings
Settings page: executor = `colab_drive`, `colab_drive_dir` = the absolute path of `~/gdrive_sanskrit` (e.g. `/home/you/gdrive_sanskrit`), device = `cuda`. Optionally set `colab_timeout_s` (Drive job timeout, default 3600 s). The manual flow has its own timeout, `colab_manual_timeout_s` (default 86400 s), settable only through the API (`PUT /api/settings`), not the Settings page.

## Daily flow (Drive mode)
1. Make sure the rclone mount is running.
2. Open `notebooks/colab_worker.ipynb` in Colab (upload it, or open it from Drive).
3. Runtime > Change runtime type > T4 GPU.
4. Run cells 1 to 5 in order (GPU check, Drive mount, file check, install + copy, smoke check). Set the `DRIVE_FOLDER` form field if you used another name.
5. Run the **MODE A** cell. It polls `jobs/` and prints activity. Leave the tab open.
6. In the app, start a job with executor `colab_drive`. The result appears in the job when `DONE` is written.
7. Stop the worker with the interrupt button when finished.

## Manual flow (no mount)
1. In the app's Generate page, download the job bundle (`bundle.zip`).
2. In Colab run cells 1 to 5, skip the MODE A cell.
3. Run the three **MODE B** cells: upload the zip, run the worker, download `result.zip`.
4. Upload `result.zip` back into the app. (The Drive folder in cell 3 must still exist for models/code; the jobs folder is not used.)

## Troubleshooting
- **Disconnects / idle timeout:** free sessions end after idle time or a maximum duration, and the VM is wiped. Rerun cells 1 to 5 and Mode A. Jobs left `READY` without `CLAIMED` are picked up again; a job with `CLAIMED` but no `DONE` may need to be re-created in the app.
- **No GPU available:** cell 1 stops. Retry later or change runtime; free GPU access is not guaranteed.
- **Drive sync delay:** the app reads files through the rclone mount; results can lag seconds to minutes. Lower `--dir-cache-time`/`--poll-interval` as shown. The worker should see `READY` only after the files are uploaded.
- **Out of memory:** restart the runtime (Runtime > Restart session), run one job at a time, reduce steps.
- **Job timeout:** raise `colab_timeout_s` in Settings if the first job (model load from Drive) is slow.
- **torch version mismatch:** if import or pip errors mention torch/torchaudio, do not force-install 2.8 blindly; read the error, try Colab's default torch, or `pip install torch==2.8.* torchaudio==2.8.*` then restart the session.
- **Pip conflicts:** the f5-tts install is pinned to the IndicF5 commit; if it clashes with preinstalled packages, tell the maintainer the exact error.

## Privacy
Verse text and the reference clip are stored in your Google Drive and processed on Google's machines. Do not use this for material you cannot share with Google.

## Terms
The Drive hand-off uses no tunnel or inbound connection. I have not verified Colab's policies; check Colab's current usage limits and terms of service before relying on it.
