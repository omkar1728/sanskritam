# TODO

Follow-ups to look at later. Newest first within each section.

## Epics browser + Colab batch audio (2026-11-01, details in `docs/progress-epics-colab-batch.md`)
Built and tested with fakes only (85 backend / 41 frontend tests); nothing from this work is committed.
- [ ] Load the real DB: `uv run python -m backend.app.epics_import` (only throwaway schemas were used so far).
- [ ] Run the NEW `notebooks/colab_batch.ipynb` on real Colab (the first real run used the older notebook). Unverified: pip/torch install, Drive write lag, GPU/RAM headroom with 2 workers.
- [ ] Measure `WORKERS=1` vs `WORKERS=2` (seconds/verse in the run summary). Keep 2 only if ~1.5x faster. Session: 2 vCPU, 12 GB RAM, T4; per worker ~3.6 GB RAM, ~2.2 GB GPU, ~15 s/verse.
- [ ] Try both ways in: "Import from Drive folder" (Settings `colab_drive_dir` must point at the mounted Drive folder) and "Upload results.zip".
- [ ] USER-CHECK: audio quality; are the auto-suggested meters right (sarga 1: 71 anushtubh, 37 `vrutta1`, 2 upajati)? Learn highlights; Devanagari look and mobile layout of the Epics pages and Generate > Epic verses; light theme of the Epics pages (the verifier's light screenshot came out dark).
- [ ] Batches are capped at 2000 jobs: a whole kanda (Bala = 2275 renderable verses) needs several batches. Maybe add a "split into batches" option.
- [ ] A second batch started before the first finishes duplicates jobs (only `done` jobs are skipped); `awaiting_result` jobs cannot be cancelled. Fix both.
- [ ] `baala-001-058` has no text in any source, so it cannot be generated; ask where its text should come from (never invent it).
- [ ] Move the `SS_FAKE_RENDER=1` test hook out of `default_render_factory` in `backend/worker/colab_worker.py`.
- [ ] Check Colab's terms for long unattended batches. Alternatives discussed, not built: EC2 over SSH, EC2 with an S3 hand-off (self-stopping instance), Kaggle API, other rented GPUs.
- [ ] Epic tables are not in the SQLite mirror backup; re-run the import after a restore (or add them to `backup.TABLES`).
- [ ] Before committing: `frontend/index.html`, `package.json`, `theme.css`, `player.css`, `Android/`, `SourceFilter.tsx` and `AlignDrop.tsx` were not changed by this work (they look like your Android/alignment work); `sources/` is untracked (323 MB), so decide whether to commit it.

## Alignment speed (look at this next)
- [ ] **Alignment is slow (~16 s per chant, ~14 min for 52).** `backend/engine/align.py` loads MMS_FA and `queue._align` calls `A.unload()` after every job, so the model is reloaded each time. Ideas: keep the model loaded for the whole batch (unload only when the queue goes idle), re-align in one process with `realign.py` (load once), reuse the torchaudio resample, try GPU/ONNX, and measure where the 16 s goes (load vs forced_align) before changing anything.
- [ ] Add a "Re-align" action in the UI (button on a job/batch) that calls the same code as `backend.app.realign`, instead of the CLI.
- [ ] Alignment speed matters most for a whole kanda: ~2300 chants x 16 s is ~10 h.

## In progress when this was written (2026-11-01)
- [x] DONE: `realign` finished (51/51), data re-exported, APK rebuilt and installed. (Original steps, for reference:) re-run `uv run python Android/export_data.py --base http://127.0.0.1:8000 --out Android/staticdata`, then `cd Android && npm run apk`, then `adb install -r Android/app-debug.apk`. Then every verse in Bāla sarga 1 should show the highlighting player.
- [ ] Batch 2 (Bāla sarga 2, 45 verses) is waiting for its Colab results zip: drop it into the "Align results zip" box.

## Quality / USER-CHECK (nobody has listened yet)
- [ ] Do highlights land on the audible words (aligned chants)? Are syllable highlights acceptable on chants flagged with `syllable_count_note`?
- [ ] Does audio play inside the Android WebView, and is scrolling a long sarga smooth with the inline players?
- [ ] Investigate the syllable-count mismatch (R8 in plan.md): which counter is right for conjuncts (ज्ञ etc.)? Fix `n_aksharas` or the aligner's syllabifier so the strict check can come back.

## Backend reliability
- [ ] **Worker hang (R9 in plan.md):** jobs stuck at "aligning 0.99" and the queue stopped until the backend was restarted. Find the root cause (storage upload to MinIO hanging? DB connection?). Add a timeout/watchdog so a stuck job is failed and the worker keeps going.
- [ ] `/api/jobs` is capped at 100 rows; add paging/filters (the Android export works around it through the verses list).

## Android app
- [ ] Epic home shows the full "7 Kandas · 26100 verses" even though only Bāla is bundled; show what is actually in the app.
- [ ] Release signing and a proper APK/AAB instead of the debug build.
- [ ] Bundle more kāṇḍas as chants are produced (size grows: ~0.25 MB per chant). Mahābhārata stays out (BORI licence).
- [ ] Offline app could allow local-only things (e.g. favourites) without the backend.
