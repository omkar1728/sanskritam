# Android (Capacitor) offline app

Standalone, read-only app: the same React UI as `frontend/`, built with `VITE_STANDALONE=1`, so GETs read bundled files from `data/` and write actions show "Not available in the offline app: needs the desktop backend".

## Rebuilding from a fresh checkout
`Android/staticdata/` (~51 MB) is **gitignored**, as are `node_modules/`, `www/`, `local.properties` and `*.apk`. A clone has none of them, so the data must be regenerated from the running backend before the app can be built. It is a snapshot of the API, so it needs everything the API serves:

1. `docker compose up -d` (Postgres :5433 + MinIO :9000; set `LOCAL_UID`/`LOCAL_GID`).
2. Restore the library: `uv run python -m backend.scripts.restore_from_sqlite --sqlite backups/sloka_mirror.sqlite` (verses, jobs, alignments). Audio MP3s are **not** in the mirror: restore `blobdata/` (MinIO data) or your bucket from your own backup, otherwise chants have no audio.
3. Re-import the epics (not in the mirror; also gitignored): `uv run python -m backend.app.epics_import` from `sources/ramayan/unified` (see `sources/ramayan/README.md`). Only the Ramayana Bāla kāṇḍa is exported.
4. Start the backend: `uv run uvicorn backend.app.main:app --port 8000`.
5. Export: `uv run python Android/export_data.py --base http://127.0.0.1:8000 --out Android/staticdata`. Note the script's default `--base` is `:8001`, so pass it explicitly. Expect roughly 2369 verses (epic) plus the library verses, jobs with audio/alignment, and ~51 MB total; the script prints counts and size.

Keep a copy of `Android/staticdata/`, `blobdata/` and `backups/` somewhere safe if you cannot regenerate them.

## Steps
1. Export data as above -> `Android/staticdata/`.
2. `cd Android && npm install` (first time).
3. `npm run build:web` builds the frontend into `www/` and copies `staticdata` to `www/data`.
4. `npm run sync` copies `www/` into the Android project.
5. `export ANDROID_HOME=/home/omkar/Android/Sdk` (also set `sdk.dir` in `Android/local.properties` and `Android/android/local.properties`), Java 17.
6. `npm run apk` does steps 3-5 plus `gradlew assembleDebug` and copies the result to `Android/app-debug.apk`.
7. Install: `adb install -r Android/app-debug.apk`.

## Maintenance
UI source is shared with `frontend/`; after any frontend or data change just re-run `npm run apk`. Nothing is duplicated. `staticdata` is not committed (see above); regenerate it with `export_data.py` (it also reads every job that has audio from the verses list, since `/api/jobs` only returns the latest 100).

## What is bundled
Library (verses + jobs with audio/alignment), and the Ramayana Bāla kāṇḍa only (77 sargas, 2369 verses). The Mahābhārata is not included (BORI licence, size). Epic reader: each verse that has a chant embeds the full Learn player (highlighted text, controls, word meanings; `frontend/src/pages/epics/InlineChant.tsx`), loaded lazily when scrolled near. Chants without alignment fall back to the plain audio bar.

## Phone testing
`adb devices -l` must list the phone as `device` (USB debugging on; on vivo also allow the debugging prompt). `adb install -r Android/app-debug.apk`.
