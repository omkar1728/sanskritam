# Sanskrit Śloka Studio

Generate slow, clear Sanskrit chant audio and learn from it with word- and syllable-level highlighting, word meanings and a verse summary. MVP.

- Backend: FastAPI + Postgres + S3-compatible blob storage. Frontend: React (Vite, TypeScript, dark theme).
- TTS: Vāgdhenu / IndicF5 DiT + BigVGAN, CPU locally or GPU on Colab. Alignment: torchaudio MMS_FA.
- Design and decisions: `plan.md`. Contributor notes: `CLAUDE.md`. Colab: `COLAB.md`. Blob storage: `STORAGE.md`.

## Not in git (fetch separately)
`EdgeSanskrit-TTS/` (about 4.4 GB: upstream code, BigVGAN and the model weights) is gitignored. Place it at the repo root with `vagdhenu/models/{voice_steer_ema_2026-06-17.pt, voice_armA_ema_2026-06-11.pt, voc_bigvgan_EMA_2026-06-11.pth, vocab.txt}`, `vagdhenu/src/` and `BigVGAN/`. Without it the app starts but cannot render.

## Run
```bash
cp .env.example .env                       # defaults match docker-compose.yml
export LOCAL_UID=$(id -u) LOCAL_GID=$(id -g)
docker compose up -d                       # Postgres :5433, MinIO :9000 (console :9001)
uv sync
uv run uvicorn backend.app.main:app        # API on :8000
cd frontend && npm install && npm run dev  # UI on :5173
```
Verses: add them in the Library, or put a list in `backend/seed/verses.json` (format in `plan.md` §12; optional `meanings`). Sources are mandatory; nothing is invented.

## Data
- **Postgres** holds verses, meanings, jobs, settings. **S3 storage** holds the mp3/wav/alignment objects (keys `jobs/<id>/...`).
- **SQLite mirror:** the database is snapshotted to `backups/sloka_mirror.sqlite` every 60 s when it changes (`BACKUP_*` in `.env`; `GET/POST /api/backup`). Restore: `uv run python -m backend.scripts.restore_from_sqlite --sqlite backups/sloka_mirror.sqlite`. Audio objects are not in the mirror; back up `blobdata/` (or your bucket) separately.
- **Meanings** are per word (meaning + optional grammar) and a verse summary, each marked `seed`, `user` or `machine`. Machine drafts are shown as unreviewed until you review them. The bundled test verse's meanings are a machine draft.
- Importing the earlier SQLite-era data: `uv run python -m backend.scripts.import_sqlite --sqlite backend/storage/app.db`.

## Test
`uv run python -m pytest backend/tests -q` (needs `docker compose up -d`; one test loads the alignment model, about 1.2 GB RAM). Frontend: `npm run build && npm run lint && npm test`.

## Status and caveats
Rendering takes minutes on CPU. Audio quality, highlight accuracy and slow-playback quality have not been judged by ear. The Colab executors are tested with fakes only. SSH executor and the Claude-drafted meanings pipeline are not built.

## Epic audio batches and the Android app
- Generate (epic mode): create a batch, download `batch.zip`, run `notebooks/colab_batch.ipynb`, then drop the resulting `results.zip` into the "Align results zip" box (`PUT /api/alignment/upload`; the batch is detected from the zip, alignment runs automatically, one chant at a time).
- Re-align finished chants that have no alignment: `uv run python -m backend.app.realign [job ids]`.
- Epic reader: verses with chants embed the Learn player inline.
- Android offline app: see `Android/README.md` (`Android/staticdata/` is gitignored; that file explains how to regenerate it). Open follow-ups: `todo.md`.
