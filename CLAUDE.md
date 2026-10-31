# Sanskrit Śloka Studio

Local app that generates slow Sanskrit chant audio (Vāgdhenu / IndicF5 DiT + BigVGAN) and teaches from it with word/syllable-synced highlighting. `plan.md` is the source of truth for decisions, data model, risks and phases; keep its Status line current.

## Layout
- `backend/app/` FastAPI, Postgres (psycopg, `db.py`; `?` placeholders translated), S3 storage (`storage.py`, MinIO/AWS/Dokploy), SQLite mirror backup (`backup.py`), job queue (one worker thread), config in `config.py`/`.env`.
- `backend/engine/` `synth.py` (render), `textprep.py` (chant text fixes, copied verbatim from the validated renderer), `align.py` (MMS_FA forced alignment), `meter.py`, `mp3.py`.
- `backend/executors/` `base.py`, `local.py` (SSH and notebook executors not written). `backend/worker/run.py` is the subprocess entry.
- `backend/tests/` pytest. `backend/seed/verses.json` is supplied by the user (does not exist yet).
- `frontend/` Vite + React + TypeScript (Library, Generate, Learn, Settings). Player code in `src/player/`.
- `docker-compose.yml` Postgres :5433 + MinIO :9000. `backups/` SQLite mirror, `blobdata/` MinIO data (both gitignored).
- `EdgeSanskrit-TTS/` (gitignored) downloaded weights and upstream code. Do not modify.
- `POC/` earlier experiments, spike scripts and outputs. Anything not needed by the app goes here, not in the app tree.

## Commands
- Backend: `uv run uvicorn backend.app.main:app` (port 8000). Tests: `uv run pytest backend/tests -q`.
- Frontend: `cd frontend && npm run dev` (proxies /api to 8000); `npm run build`, `npm run lint`, `npm test`.
- Services: `docker compose up -d` (set LOCAL_UID/LOCAL_GID). Tests: `uv run python -m pytest backend/tests -q`; they use the `sloka_test` database and an in-memory store, never the real `sloka` DB. Never touch the `leetclone_db` container (port 9999, another project).
- Port 8000 may already be held by the user's own dev server; test on another port and do not kill it.

## Constraints
- **RAM is 6 GB; one render needs ~3.4 GB, alignment (MMS_FA) ~1.2 GB.** Never run two model processes at once, including in parallel subagents. Real renders take minutes; tests use a fake executor and the POC wav (`POC/outputs/gita_2_47_default.wav`).
- **Claude cannot hear audio.** Anything about sound quality, or highlights matching audible words, is a "USER-CHECK" item, never reported as passed.
- **Never invent verse text or citations.** Verses and sources come from the user. Test fixtures must be clearly marked as fixtures.
- Alignment times are shifted to match the MP3 lead-in (`mp3.LEAD_MS`); the player plays the MP3.
- Git: commit only when asked; end commit messages with the Co-Authored-By trailer. `EdgeSanskrit-TTS/` is never committed.
- Meanings from `machine` origin are drafts: never present them as reviewed.

## Workflow
Use the `feature-workflow` skill (`.claude/skills/feature-workflow/`) for any feature or multi-file change: clarify with the user, split into disjoint-file tasks for `implementer` subagents, verify with `verifier` subagents, max two attempts per task, then update `plan.md` and report USER-CHECK items.
