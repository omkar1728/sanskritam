---
name: feature-workflow
description: Mandatory workflow for implementing any feature or multi-file change in Sanskrit Śloka Studio (backend/ FastAPI + engine, frontend/ React, executors, worker). Clarify first, split into parallel implementer subagents, verify with verifier subagents, loop until done. Use before starting any feature work.
---

# Feature workflow

Main thread = orchestrator. Keep it light: no large file reads, no code dumps. Only plans and subagent reports enter it. `plan.md` is the source of truth for decisions, data model and phases; read it (or the relevant section) instead of re-deriving.

## Project constraints (apply to every task)
- **RAM is 6 GB total; one model job needs ~3.4 GB.** Never run two torch/render/alignment processes at once, and never in parallel subagents. At most ONE agent may run a real render or load MMS_FA at a time; all others use fakes (fake executor, POC wav in `POC/outputs/`).
- Real renders take minutes. Verifiers use the fake executor and the existing POC wav unless the criterion truly needs a real render.
- **Nobody can hear audio.** Any criterion about how it sounds, or whether highlights land on audible words, goes to the user as a "listen and confirm" item. Do not mark it PASS.
- Never invent verse text or citations. Verses come from the user's `backend/seed/verses.json`; test fixtures must be clearly marked as fixtures.
- Everything not part of the app (experiments, scratch scripts, spike outputs) goes in `POC/`, not the app tree.
- Python via `uv run`. Weights live in `EdgeSanskrit-TTS/`; do not modify that directory.
- Not a git repo: no commits or PRs unless the user initialises git and asks.

## 1. Clarify (before any implementation)
- Minimal exploration (an Explore subagent, or a targeted grep; not raw reads of big files).
- Ask every open doubt via AskUserQuestion. Do not start until resolved.
- Write acceptance criteria: a short checklist, each item objectively checkable (API response, test passes, UI behaviour in the browser, build clean). Mark listening items as `USER-CHECK`.

## 2. Plan
- Split into tasks. Each task lists the exact files it owns.
- File sets MUST be disjoint across parallel tasks; if two tasks need the same file, run them sequentially.
- Natural boundaries: `backend/app` (API/DB/queue), `backend/engine` (synth/align), `backend/executors` + `backend/worker`, `frontend/`. Define the contract (endpoint shapes, `alignment.json` schema, DB columns) in the plan so tasks don't depend on each other's output.
- Show the plan to the user in a few bullets, then proceed.

## 3. Implement (parallel where safe)
- Spawn one `implementer` subagent per task, all in a single message. Single shared working tree; no worktrees.
- Give each: goal, owned files, contract, acceptance items, "do not touch other files", and the RAM rule above.
- Each returns a report of at most 150 words: files changed, notes, open issues.

## 4. Verify
- Spawn `verifier` subagents after implementers finish (one per feature area; parallel only if neither loads a model).
- Backend: `uv run pytest backend/tests -q`, curl the endpoints against `uv run uvicorn backend.app.main:app` (use a temp `SS_STORAGE`/`SS_DB`, not the real storage).
- Frontend: `npm run build` and `npm run lint` in `frontend/`; UI behaviour checked in a real browser with Playwright against the running dev server (click a word, assert playback range and highlight state; check the dark theme and Devanagari rendering via screenshot).
- Verifier is read-only on source; returns PASS/FAIL/USER-CHECK per acceptance item with evidence, at most 150 words.

## 5. Loop
- On FAIL: spawn a new `implementer` with the verifier's findings, then re-verify.
- Max 2 tries per task (initial + one retry). If still failing, STOP and ask the user to intervene, with a summary of what failed.
- Repeat until all non-USER-CHECK items pass.

## 6. Finish
- Update `plan.md`: the Status line and any decision or risk that changed.
- Add or update tests for the feature; `uv run pytest backend/tests -q` and (once it exists) `npm run lint && npm run build` must be clean.
- Report to the user: what changed, verification results, and the explicit list of USER-CHECK items to listen to or try.
