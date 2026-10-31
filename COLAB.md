# Running renders on Google Colab (free T4)

**Status: this has NOT been run on real Colab by the author.** The notebook and these steps are written from the repo's code and pins only. The steps most likely to need adjustment:
1. The pip install cell (dependency resolution against Colab's preinstalled packages).
2. torch/torchaudio versions (the repo pins 2.8; Colab ships its own and the notebook does not reinstall torch).
3. rclone mount latency (the app may wait on Drive sync).

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
