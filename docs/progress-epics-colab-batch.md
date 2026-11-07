# Progress: Epics browser and Colab batch audio (handoff)

Last updated 2026-11-01. Nothing from this work is committed. `plan.md` (Status line, section 3, R2) and `COLAB.md` are also updated; this file is the pick-up-here summary.

## What exists

### 1. Epics browser (Epics > Ramayana > Kanda > Sarga > verses)
- Data: `sources/ramayan/unified/<kanda>/sarga_NNN/verse_NNN.json` (supplied by the user; see `sources/ramayan/README.md`). 26,100 verses, 651 sargas, 7 kandas. Every meaning is `unreviewed`.
- Import into Postgres, rerunnable and idempotent: `uv run python -m backend.app.epics_import`. Tables `epic_sargas`, `epic_verses` (full verse JSON as JSONB), migration v2 in `backend/app/db.py`. Not in the SQLite mirror backup; re-import after a restore.
- API: `backend/app/epics.py` (`/api/epics/...`, read-only).
- UI: `frontend/src/pages/epics/`. Reader toggle between text variants (critical, vulgate net, vulgate .in, Gita Press OCR), all meanings in collapsible sections with source and unreviewed/unverified badges.
- The real dev DB has NOT been imported into yet by us (verification used throwaway schemas). Run the import command once.

### 2. Epic audio via Colab batch (Generate > Epic verses)
Flow: pick scope (verse / sarga / kanda / whole Ramayana) > app copies critical-text verses into `verses`, auto-suggests meter per verse (optional override for the whole sarga), creates jobs in status `awaiting_result` (executor `colab_batch`) > download `batch.zip` > run `notebooks/colab_batch.ipynb` (one cell) in Colab > results land in the user's Drive > bring them into the app.
- Backend: `backend/app/epic_jobs.py` (materialise, preview, create), `backend/app/batch_io.py` (batch.zip builder, results ingest from zip and from a Drive folder), `backend/executors/staged.py` (`colab_staged`), routes in `backend/app/main.py` under `/api/epic-batches`. Migration v3 adds `epic_batches` and `jobs.batch_id`.
- One batch is capped at 2000 jobs, so a whole kanda (Bala = 2275 renderable verses) needs several batches.
- `batch.zip` contains `batch.json`, `refs/<meter>.wav` and `code/backend/...` (worker code, so a stale Drive copy cannot break a run). `batch.json` carries `results_root`, `batch_dir` and a per-job `result_dir`.
- Drive layout (config comes from batch.json):
  `<Drive>/<folder>/batch_results/ramayana/<kanda>/sarga_NNN/<verse_id>/{chant.wav,result.json}` and `batch_results/_batches/<batch_id>/{errors.json,results.zip}`. `result.json` is written last and is the completion marker, so reruns resume.
- Worker: `backend/worker/colab_worker.py` batch mode, `--workers N` (any N, no hard cap; prints a WARNING if N exceeds RAM/CPU estimates), `--shard i/N`, `--results-root`. Notebook field `WORKERS`; `DOWNLOAD_ZIP` is off by default.
- Into the app: "Import from Drive folder" (`POST /api/epic-batches/{id}/import-drive`, needs Settings `colab_drive_dir` pointing at the locally mounted Drive folder) or "Upload results.zip" (accepts `results/<job_id>/...` and bare `<job_id>/...`). Imported jobs go through the usual MP3 + MMS_FA alignment on this machine.
- Frontend: `frontend/src/pages/generate/EpicBatch.tsx` (+ helpers, css), switch added in `Generate.tsx`.

## Measured on real Colab (user-reported, first run)
~15 s per verse, ~3.6 GB system RAM, ~2.2 GB GPU RAM per worker. Colab session: 2 vCPU, 12 GB RAM (10 GB available), T4 15 GB. First setup ~10 min. Extrapolated (not measured): 110-verse sarga ~28 min, all of Bala ~9.5 h, whole Ramayana ~109 h. Details in `COLAB.md`.

## Verified (with a fake renderer only; no real Colab, no real TTS, nobody listened)
85 backend tests, 41 frontend tests, lint and build clean. End-to-end on the real Bala data in throwaway schemas: batch creation, batch.zip contents, notebook cell logic with Colab stubbed (2 workers, failures, resume, Drive layout), both import paths, and the browser flow.

## Not done / open
- **Never run on real Colab with the new notebook**: the first run happened with the older notebook. Pip/torch install steps, Drive write lag, GPU/RAM headroom with 2 workers are unverified.
- **Parallel speed-up unmeasured.** Compare seconds/verse with `WORKERS=1` vs `2` (the run summary now counts only verses rendered in that run, incl. model load). Keep 2 only if about 1.5x faster or better.
- **Alignment/MP3 time on this machine unmeasured** (MMS_FA ~1.2 GB RAM, one job at a time).
- **USER-CHECK (nobody can hear/see these):** audio quality; whether the auto-suggested meters are right (sarga 1 got 71 anushtubh, 37 `vrutta1`, 2 upajati); Learn highlights landing on audible words; Devanagari look and mobile layout of both new UIs; light theme of the Epics pages (the verifier's light-mode screenshot came out dark).
- `baala-001-058` has no text in any source, so it is "unavailable" and cannot be generated.
- A second batch started before the first finishes duplicates jobs (only `done` jobs are skipped). `awaiting_result` jobs cannot be cancelled yet.
- Colab terms of use for long unattended batches not checked. EC2 (options A/B in the conversation: SSH executor, or S3 hand-off with self-stopping instance), Kaggle and other rented GPUs were discussed but not built.
- `SS_FAKE_RENDER=1` is a test hook inside `default_render_factory` in `colab_worker.py`; consider moving it out of production code.

## Files changed by this work
Modified: `backend/app/{db,main}.py`, `backend/executors/{bundle,local}.py`, `backend/worker/colab_worker.py`, `COLAB.md`, `plan.md`, `frontend/src/{App.tsx,api.ts,types.ts}`, `frontend/src/pages/Generate.tsx`.
New: `backend/app/{epics,epics_import,epic_jobs,batch_io}.py`, `backend/executors/staged.py`, `backend/tests/{test_epics,test_epic_batch,test_colab_batch}.py`, `frontend/src/pages/epics/*`, `frontend/src/pages/generate/{EpicBatch.tsx,epicBatch.css,epicBatchHelpers.ts,epicBatchHelpers.test.ts}`, `notebooks/colab_batch.ipynb`, `docs/`.
Present in the working tree but NOT from this work (origin unknown, check before committing): `frontend/index.html`, `frontend/package.json`, `frontend/src/theme.css`, `frontend/src/player/player.css`, `Android/`, `frontend/src/pages/epics/SourceFilter.tsx`, `frontend/src/pages/generate/AlignDrop.tsx`. `sources/` is untracked (decide whether to commit it; 323 MB).

## How to resume
1. `docker compose up -d`; `uv run python -m backend.app.epics_import` (loads the real DB).
2. Start the app, Generate > Epic verses > Bala sarga 1 > create batch > download `batch.zip`.
3. Run `notebooks/colab_batch.ipynb` on a T4 with `WORKERS=1`, then again on another sarga with `WORKERS=2`; note seconds/verse.
4. Import from Drive folder (set `colab_drive_dir` in Settings) or upload `results.zip`; open Learn pages and listen.
5. Then decide: commit (ask first, CLAUDE.md), real-Colab fixes, EC2/other GPU route, cancel for `awaiting_result` jobs, duplicate-batch guard.
