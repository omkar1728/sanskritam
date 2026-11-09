# Śloka audio pipeline: specification

Status: **DRAFT v0.2 (2026-11-09). Nothing implemented.** Scope: **Ramayana only** for now. v0.2 applies the owner's answers of the requirements interview (section 2, D7-D22) and removes the contradictions of v0.1. Items marked **[OPEN]** are not yet decided and do not block Ramayana work unless stated.

> **For a fresh Claude Code session:** this file is meant to be self-contained. Read section 0 (context) first, then sections 1-11. The owner keeps refining this spec; do not start implementing until they say so. Section 2 is the authoritative decision list; if any other text seems to disagree with it, section 2 wins and the disagreement is a bug in this file to report.

## 0. Context (everything a new session needs)

### 0.1 Project
Repo `/home/mahaomk/my_codes/sanskritam` ("Sanskrit Śloka Studio"): a local app that generates slow Sanskrit chant audio with **Vāgdhenu** (IndicF5-style DiT + BigVGAN vocoder) and teaches from it with word/syllable-synced highlighting. `CLAUDE.md` (repo root) and `plan.md` are the sources of truth for the app; `plan.md` has a Status line that must be kept current when work lands. App layout: `backend/app/` FastAPI + Postgres + S3 storage + job queue, `backend/engine/` (`synth.py` render, `textprep.py` chant text fixes, `align.py` MMS_FA forced alignment, `meter.py`, `mp3.py`), `backend/executors/`, `backend/worker/run.py`, `frontend/` (Vite/React), `POC/` (earlier experiments), `EdgeSanskrit-TTS/` (gitignored weights + upstream code; **never modify, never commit**). The new `pipeline/` folder (this spec) is a standalone batch tool; it may import `backend.engine.*` but not `backend.app`.

Rules from the repo `CLAUDE.md` that apply here:
- **Never invent verse text or citations.** Verses come from the owner; test fixtures must be clearly marked as fixtures.
- **Claude cannot hear audio.** Anything about sound quality or highlights matching audible words is a "USER-CHECK" item, never reported as passed.
- Local dev machine has 6 GB RAM: one render needs ~3.4 GB, alignment (MMS_FA) ~1.2 GB; never run two model processes at once locally (on the 15 GB EC2 box this is a performance matter, see 0.4).
- Alignment times are shifted by `mp3.LEAD_MS` (400 ms) because the player plays the MP3, not the WAV.
- Git: commit only when asked; commit messages end with the Co-Authored-By trailer given by the harness. Meanings from `machine` origin are drafts, never presented as reviewed.
- Feature work is supposed to follow the `feature-workflow` skill (`.claude/skills/feature-workflow/`): clarify with the user, split into disjoint-file tasks for `implementer` subagents, verify with `verifier` subagents, max two attempts per task, update `plan.md`, report USER-CHECK items. Tests: `uv run python -m pytest backend/tests -q` (they use the `sloka_test` database and fake executors, never real models). Port 8000 may be held by the owner's dev server: do not kill it.
- Chat style requested by the owner's global config: terse ("caveman mode"): short sentences, no filler, bullets/tables; code and documents stay normal quality.

### 0.2 Existing data and flows the pipeline must fit
- Ramayana corpus: `test_data/ramayan/unified/<kanda>/sarga_NNN/verse_NNN.json` (391 files locally in `test_data/`; the full set is 26,100 verses in 651 sargas / 7 kandas, supplied by the owner, imported into Postgres tables `epic_sargas` / `epic_verses` by `uv run python -m backend.app.epics_import`; API `backend/app/epics.py`). Verse JSON fields: `id` (e.g. `baala-001-001`), `kanda`, `sarga`, `seq_in_sarga`, `refs`, `kind`, `text.{critical_smith,vulgate_net,vulgate_in,vulgate_gitapress}.lines` (list of padas), plus cross-variant `alignment` diffs. Variant priority used by the POCs: `vulgate_net`, `vulgate_in`, `critical_smith`; the app's epic-audio flow uses the critical text. `vulgate_net` uses ङ् (not anusvara) before velars.
- Existing app render path: `queue._run` renders with `Engine.render(RenderSpec)`, aligns with `queue._align` (align, `validate`, soft-accept syllable-count mismatch, `A.shift(LEAD_MS...)`, falls back to line-level timing on failure), encodes with `mp3.wav_to_mp3` (192 kbps mono 44.1 kHz, loudnorm, 400 ms lead-in, 0.3 s tail). Alignment JSON schema is `{audio_duration, lines:[{words:[{line, slp1, text, start, end, syllables:[{slp1,start,end}]}]}], syllable_count_note?}`.
- Existing Colab batch flow (`docs/progress-epics-colab-batch.md`, `COLAB.md`, `notebooks/colab_batch.ipynb`, `backend/app/batch_io.py`, `backend/executors/staged.py`): app builds `batch.zip` (<= 2000 jobs), user runs a Colab cell, results land on Drive as `<verse_id>/{chant.wav,result.json}` per verse, then are imported. This works but writes one folder per verse (does not scale to 100k+). The pipeline does **not** replace it: both live side by side (D9). A real Colab T4 run took ~10 min for first-time setup.
- Reference bank: `EdgeSanskrit-TTS/vagdhenu/src/reference_bank/bank.json` (18 clips: wav, ref_text, sec_per_syll, mode). Ramayana slokas use the `anuṣṭubh` clip.
- Defaults in `backend/app/config.py`: `DEFAULT_STEPS = 16`, `DEFAULT_SEED = 50`. The owner decided on **10 steps** for the pipeline; `DEFAULT_STEPS` in the app stays 16 (D17: pipeline only, app untouched). Model files: `EdgeSanskrit-TTS/vagdhenu/models/{voice_armA_ema_2026-06-11.pt, voice_steer_ema_2026-06-17.pt, voc_bigvgan_EMA_2026-06-11.pth, vocab.txt}`; `Engine._load` uses voc BigVGAN config `BigVGAN/configs/bigvgan_v2_24khz_100band_256x.json`. Render spec defaults in `synth.RenderSpec`: speed 0.90, cfg 3.0, gap 0.55, gap_halant 0.20.

### 0.3 What was done in this conversation (history)
1. **Model POC** (`POC/model_poc/`, files `common.py`, `run_vagdhenu.py`, `run_indicf5.py`, `run_parler.py`, `run_align.py`, `compare.py`, `run_all.sh`, `ec2_env.sh`, `ec2_setup.sh`, `NOTES.md`): compared Vāgdhenu, IndicF5 and Indic Parler-TTS on the first 10 verses of Ramayana Bala sarga 1. Owner listened: **Vāgdhenu good; Parler has no meter (plain recitation); IndicF5 syllables jumbled/unintelligible.** Decision: Vāgdhenu only. Results from the EC2 run are in `POC/model_poc/results_s3/ba-sarga1-2026-11-08/` and `.../benchmark-2026-11-08/` (includes the owner's `results.md` with all AWS hurdles).
2. **Step-size POC** (`POC/model_poc/run_vagdhenu_steps.py`, `summarize_steps.py`, `run_steps.sh`, `vagdhenu_stepsize.md`): same verse (`baala-001-001`, seed 50, `voice_armA`, `anuṣṭubh` ref) at steps 2-14 and 16-64, 3 repeats each, on a T4. Data pulled to `POC/model_poc/results_s3/vagdhenu-stepsize-2026-11-09/` (54 wavs under `audio/vagdhenu_steps/`, tables under `results/` and `results/low_steps/`). Owner listened: **no perceptible difference above 10 steps.** Anomaly (cause unknown, not investigated): steps 2, 4, 6 take 5.9 / 10.5 / 11.7 s and give longer audio (9.85-10.0 s) than steps 8+ (the 8-30 range follows the linear fit).
3. **Cost analysis**: S3 vs EBS for keeping weights (S3 wins: ~$0.075/month for 3.0 GiB vs ~$0.46-1.82/month on EBS; EBS needs 30-140 launches/month to break even; an AMI with driver + venv baked in, ~$0.60/month, is the real fix for the 3-minute setup). Live ap-south-1 prices were fetched via `aws pricing get-products --region us-east-1 ...` and `aws ec2 describe-spot-price-history`. Re-run them before committing to numbers; spot prices move.
4. Owner then asked for this pipeline spec. Questions asked and the **owner's answers verbatim**:
   - Input: *"i plan to store the texts like ramanyana and mahabharat in one big file or a group of files that can be read and used by database services like sql or nosql, the technologies are yet to be decided, based on the requirements provide me suggestions with pros and cons"* -> section 5.3.
   - Output: *"The verse count would eventually reach a hundred thousand plus, so need a scalable solution just like the input format I stated earlier, multiple small files would slow down the read write speed"* -> section 6 (packed shards).
   - Parallelism: chose "multi-process only", *"also consider if we can use a different gpu other than T4"* -> sections 4.3-4.5.
   - Destination: *"S3 when the job runs on aws, google drive when it runs on colab"* -> section 7. Writing to Postgres and importing into the app are out of scope (D13).

### 0.4 AWS environment (from the owner's `results.md` and this session)
- Account `785703562757`, region `ap-south-1`. AWS CLI works on the dev machine as IAM user `ecr-pusher` (it could create IAM roles and read pricing).
- S3 bucket `s3://sloka-poc-audio-785703562757` (private): `results/ba-sarga1-2026-11-08/`, `results/benchmark-2026-11-08/`, `results/vagdhenu-stepsize-2026-11-09/{audio,results}/`, `setup/EdgeSanskrit-TTS/` (3.2 GB / 3.0 GiB; the only weights Vāgdhenu needs), `setup/hf/` (10.5 GB, IndicF5/Parler/flan-t5/vocos; no longer needed since those models were dropped; deletion was offered, not done), `setup/requirements-lock.txt` (206 packages, the working set from the EC2 run), `setup/restore.sh` (**untested**). The bucket holds copies of third-party weights: keep private, mind their licences. No HF token is stored there.
- IAM, created this session: role + instance profile `sloka-poc-ec2-s3` with inline policy `s3-poc-bucket` (ListBucket/GetBucketLocation on the bucket; GetObject/PutObject/AbortMultipartUpload on its objects), attached to instance `i-01a70ee2578fd9c20` (g4dn.xlarge, ap-south-1a). No delete rights. Cleanup commands are listed in the earlier conversation: disassociate, remove-role-from-instance-profile, delete-instance-profile, delete-role-policy, delete-role.
- EC2 box that worked (g4dn.xlarge: Tesla T4 16 GB, 4 vCPU, ~15.4 GB RAM): stock Ubuntu image has **no NVIDIA driver** -> `sudo apt install -y nvidia-driver-580-server nvidia-utils-580-server` then **reboot**; root disk is only 8 GB (~4 GB free), so the 116 GB **ephemeral** instance-store NVMe (`nvme1n1`, wiped on stop) is formatted ext4 and mounted at `/mnt/data` for venv, caches (`HF_HOME`, `UV_CACHE_DIR`, `TMPDIR`) and outputs; Python 3.11 venv at `/mnt/data/venv`; torch 2.8.0+cu126 (the repo's `pyproject.toml` pins the CPU torch index: install the CUDA build). `POC/model_poc/ec2_env.sh` automates the NVMe mount. The setup takes ~3 minutes on the owner's account of it.
- Vāgdhenu sources if S3 is unavailable: weights from HF `prathoshap/vagdhenu` (public, no token; 4 files above), code + `reference_bank` from `https://github.com/prathoshap/vagdhenu` (`src/`), `BigVGAN` from `https://github.com/NVIDIA/BigVGAN`, assembled as `EdgeSanskrit-TTS/{vagdhenu/{models,src},BigVGAN}`. One weights download failed once and worked on retry (add retries).
- Other lessons: protobuf pins from parler-tts broke wandb/sentencepiece (irrelevant now that Parler is dropped); `.gitignore` entry `EdgeSanskrit-TTS/` (trailing slash) does not ignore a symlink named `EdgeSanskrit-TTS`, so use `EdgeSanskrit-TTS` without the slash; `pgrep -f run_x` matches its own command line, use `pgrep -f "[r]un_x"`.
- Security: a Hugging Face token was pasted into an earlier session and saved on the box; it should be revoked at huggingface.co/settings/tokens. There is an untracked `tokens.txt` in the repo root: keep it out of git.

### 0.5 Measured numbers (T4, g4dn.xlarge)
| Item | Value |
|---|---|
| Render, 16 steps (app default) | 10.46 s/verse (RTF 1.09), ~9.5 s audio |
| Render, 10 steps (chosen) | **7.07 s/verse** (6.99-7.11), RTF 0.77, ~9.2 s audio; ~500 verses/hour/T4 |
| Render, 64 steps | 37.99 s |
| Cost model | ≈ 1.2 s + 0.575 s x steps per verse |
| Model load + warm-up (first render in process) | 30-35 s |
| Per process resources | 2.34 GB VRAM allocated (2.42 reserved), 2.4 GB RSS (3.3 GB peak earlier), ~99% GPU, 1 CPU core, system CPU ~27% on 4 vCPUs |
| Concurrency on one T4 (N processes x 10 verses at 16 steps) | N=1: 0.078 verses/s; N=2: 0.075; N=3: 0.077; per-verse time grows ~linearly with N: **no gain from parallel processes on a T4** |
| Other models (mean wall s/verse, 10 verses) | Vāgdhenu 13.6 (incl. 36 s first-verse load), IndicF5 17.3, Parler 14.9 |
| Not measured | alignment time per verse, MP3 encode time, any non-T4 GPU, fp16 |

### 0.6 How to regenerate the pricing/benchmark data
```
aws pricing get-products --region us-east-1 --service-code AmazonEC2 --filters Type=TERM_MATCH,Field=regionCode,Value=ap-south-1 Type=TERM_MATCH,Field=instanceType,Value=g4dn.xlarge Type=TERM_MATCH,Field=operatingSystem,Value=Linux Type=TERM_MATCH,Field=tenancy,Value=Shared Type=TERM_MATCH,Field=preInstalledSw,Value=NA Type=TERM_MATCH,Field=capacitystatus,Value=Used
aws ec2 describe-spot-price-history --region ap-south-1 --instance-types g4dn.xlarge --product-descriptions "Linux/UNIX" --start-time <iso>
# S3 / EBS: service-code AmazonS3 (storageClass "General Purpose", volumeType Standard) and AmazonEC2 (volumeApiName gp3, productFamily "Storage Snapshot")
```
Prices used in this spec (2026-11-09, ap-south-1): S3 Standard $0.025/GB-month, GET $0.0004/1000, EBS gp3 $0.0912/GB-month, EBS snapshot $0.05/GB-month, g4dn.xlarge on-demand $0.579/h. The step-size harness is `POC/model_poc/run_vagdhenu_steps.py` (samples GPU/CPU/RAM every 0.5 s); the concurrency run left only logs in `results_s3/benchmark-2026-11-08/` (the script itself was not saved here). The step-size harness is the starting point for the pipeline's `bench` command.
## Scope
A standalone, resumable batch pipeline that reads Ramayana verses, renders chant audio with Vāgdhenu, aligns it, and publishes a compact, randomly-accessible, incrementally growing store that a web server or an Android app can read directly. Ramayana is 26,100 verses (about 51 GPU-hours at 7.07 s/verse, roughly $13 on T4 spot, ~6.6 GB of MP3 at 192 kbps). The storage design targets 100k+ verses so that Mahabharata and other works fit later without redesign.

## 1. Goals and non-goals

Goals
1. One command renders and aligns any selected section of the Ramayana (all, a kanda, chapters, missing or failed verses), on AWS, Google Colab, or a local machine, choosing CPU or GPU automatically.
2. As fast as possible: multi-process GPU rendering where it helps, CPU alignment/encoding overlapped with rendering, and manual scale-out by running several instances with `--shard i/K`.
3. Standardised input (one record schema) and standardised output (one packed store per work: segments/shards + catalog) that consumers read with no pipeline code.
4. Safe on spot: interruption loses at most a few minutes of work; reruns skip finished verses.
5. Incremental: later runs add or replace verses in the same store; outputs of several instances/sessions (S3, Drive, local) are combined into one catalog by `merge`.

Non-goals (v1)
- No writes to the app's Postgres (`jobs`/`assets`) and no app import path (D13). No change to the app's `DEFAULT_STEPS` (D17).
- No spot launcher / AMI bake scripts: the owner starts instances manually and passes `--shard i/K` (D16). The sharding contract is kept so a launcher can be added later.
- No replacement of the Colab batch flow (D9).
- No new models. Vāgdhenu only. No text editing: **verse text comes from the input, never invented or altered** (only `backend/engine/textprep.py` chant fixes).
- No Mahabharata work now (source and licence undecided, O6). No training, no UI.

## 2. Decisions so far (from the owner)

| # | Decision | Source |
|---|---|---|
| D1 | Default model Vāgdhenu (`voice_armA_ema_2026-06-11.pt` + BigVGAN `voc_bigvgan_EMA_2026-06-11.pth`). | POC listening |
| D2 | Default `steps = 10`: no perceptible quality gain above 10 (T4: 7.07 s/verse vs 10.46 s at 16). | step-size POC, USER-CHECK |
| D3 | Parallelism = **multi-process** (no in-process batching); also evaluate GPUs other than the T4. Because a T4 gives no gain from extra processes (measured), the worker count is calibrated, not fixed (4.3). | answer 3 |
| D4 | Output must be scalable to 100k+ verses; many small files are not acceptable. | answer 2 |
| D5 | Destination: S3 when on AWS, Google Drive when on Colab. | answer 4 |
| D6 | Corpus storage technology (SQL/NoSQL/files) for the future is undecided (section 5.3). For Ramayana the inputs are the existing `test_data`/Postgres corpus and JSONL. | answer 1 |
| D7 | Scope is Ramayana only for now. | interview |
| D8 | Text variant: `critical_smith`. If a verse has no critical text (`kind: vulgate_only`, ~17% of the local sample), fall back to `vulgate_net`, then `vulgate_in`, and **record the fallback in the catalog** (`text_variant`, `text_fallback=1`). A verse with no usable text in any of those is `failed` (`error: no_text`) and is never skipped silently. | interview |
| D9 | The pipeline lives next to the Colab batch flow; it is also designed to run on Colab. | interview |
| D10 | Meter (reference-bank clip) is configurable: default `anuṣṭubh`; override per run (`--meter`) and per record (`meter` field). No auto-detection in v1. | interview |
| D11 | MP3 bitrate configurable (`--mp3-kbps`), default 192. Choice for release is a USER-CHECK. | interview |
| D12 | Runs are incremental. Selection by book/chapter filters, by explicit ids, and by status (`--only missing`, `--only align_failed`, `--only failed`). One store per work; the store grows run by run. | interview |
| D13 | The app does not consume pipeline output now (no importer, no Postgres writes). Consumers are web/Android readers of catalog + shards. | interview |
| D14 | Alignment failure: 2 automatic retries inline, then status `align_failed`; the MP3 is kept and shipped, and the WAV is kept in a wav pack so a later `--only align_failed` run re-aligns without re-rendering. The WAV is deleted from the store once the verse is aligned. | interview |
| D15 | "Combine multiple sources" = combine **multiple outputs** (several instances, Colab sessions, S3 and Drive copies) into one catalog. `merge` runs on the owner's local machine and is the only writer of `catalog.sqlite`. | interview |
| D16 | v1 = single-machine `run` only (no launcher). Scale-out is manual with `--shard i/K`. | interview |
| D17 | Pipeline default `steps = 10`; app `DEFAULT_STEPS` stays 16. | interview |
| D18 | Seed fixed at 50 for every verse. | interview |
| D19 | Same `verse_id` produced twice (re-render with other params, changed text, overlapping instances): **newest wins** in the catalog; older blobs remain in their segments/shards until a `gc`/`compact` pass. | interview |
| D20 | Store layout: one store per work (`<dest>/<work>/`), not one immutable folder per run (section 6). | interview |
| D21 | AWS destination: reuse the POC bucket with a new prefix: `s3://sloka-poc-audio-785703562757/pipeline/ramayana/`. | interview |
| D22 | Packed shards + catalog design kept although Ramayana alone is 26,100 verses. | interview |
| D23 | Fallback order after `critical_smith`: `vulgate_net`, then `vulgate_in`. `vulgate_gitapress` (OCR) is never used. | interview |
| D24 | Fallback verses are marked in the catalog only (`text_variant`, `text_fallback`); alignment JSON is unchanged. | interview |
| D25 | `run` is never blocked by missing calibration; `bench` is optional (warning only). The alignment/MP3 cost POC (P1, section 12) is planned and not yet done. | interview |
| D26 | `bootstrap` weights: S3 copy first, then HF `prathoshap/vagdhenu` + GitHub sources, with retries (section 7). `setup/restore.sh` is untested and must be tested before it is relied on. | interview |

## 3. Measured facts the design relies on

From the T4 (g4dn.xlarge) POC runs, 2026-11-08/09 (`POC/model_poc/results_s3/`):
- Render time is linear in steps: about 0.575 s per step plus 1.2 s fixed. Step 10 = **7.07 s/verse** (RTF 0.77, ~9.2 s audio). First render in a process adds 30-35 s (load + warm-up).
- One render process uses **2.34 GB VRAM and ~2.4 GB RAM** (3.3 GB peak seen), 99% GPU, **one CPU core**.
- **Running 1, 2 or 3 processes on one T4 gave the same throughput** (0.078 / 0.075 / 0.077 verses/s): the GPU is the bottleneck. So multi-process helps only when there is spare GPU compute (bigger GPU) or more GPUs/instances. The pipeline therefore calibrates the worker count instead of hard-coding it (section 4.3).
- Not yet measured: alignment (MMS_FA) time per verse, MP3 encode time, and any non-T4 GPU. These are the first things the `bench` command must produce.

Existing code reused (do not rewrite): `backend/engine/synth.py` (`Engine.render`, `RenderSpec`), `textprep.py`, `align.py` (`align`, `validate`, `shift`), `mp3.py` (`wav_to_mp3`, `LEAD_MS=400`, `TAIL_S=0.3`), reference bank `EdgeSanskrit-TTS/vagdhenu/src/reference_bank/`.

## 4. Architecture

```
 input (jsonl | txt dir | postgres)
        |  adapters -> JobRecord
        v
   selection: --book/--chapters/--ids/--only  ->  --shard i/n  ->  skip verses already done in the store
        |
        v
   job queue ---> render workers (GPU, N procs)  --wav-->  post workers (CPU: align + MP3)
                                                                  |
                                                                  v
                                                       segment writer (append-only, sealed)
                                                                  |
                                                       publisher (S3 | Drive | local) : sealed segments only

   later, on the owner's local machine:
   merge (--from store A --from store B ...)  ->  catalog.sqlite + manifest.json  [+ optional compact/gc]
```

### 4.1 Stages
1. **Read**: adapter yields `JobRecord`s (section 5). Validate; invalid records (including verses with no usable text, D8) go to the run's `failed.jsonl` and to the catalog as `failed` at the next merge, never stop the run. Metadata files without a `text` key (10 of 401 local files) are not verses and are skipped by the adapter, counted in the run summary.
2. **Select** (D12): filters `--book`, `--chapters`, `--ids`/`--ids-file`, `--only missing|align_failed|failed` (status taken from the store's catalog, or from the store's segment indexes when no catalog exists yet), then `--shard i/n` (stable hash of `verse_id`, so every instance computes the same split with no coordination). Then drop verses whose stored result is `ok` with equal `text_sha256` and `params_hash` (unless `--force`).
3. **Render** (GPU worker processes): `Engine.render` per verse, WAV to local scratch. Each worker loads the models once and stays warm. Sorting jobs by syllable count (longest first) reduces tail idle time. `--only align_failed` skips rendering and takes the WAV from the wav pack.
4. **Post** (CPU worker pool, separate from render workers so the GPU never waits): `align.align` + `validate` + `shift(LEAD_MS...)` (same rules as `queue._align`), then `wav_to_mp3`. On alignment failure retry up to 2 more times (D14); if still failing the verse is `align_failed`: the MP3 is kept and shipped (line-level fallback in the player, as in the app) and the WAV is written to the wav pack. Alignment runs on CPU by default; `--align-device cuda` is allowed only if VRAM headroom exists.
5. **Write**: results are appended to a *segment* (section 6.3). Scratch WAVs are deleted after the MP3 exists, except WAVs of `align_failed` verses (wav pack) or with `--keep-wav`.
6. **Publish**: each sealed segment is copied to the destination store as soon as it is complete (S3 multipart / Drive copy). `run` never touches `catalog.sqlite`.

### 4.2 Hardware detection (`--device auto`)
Order: explicit `--device` / env `PIPELINE_DEVICE` wins; else CUDA available -> `cuda`; else `cpu`. (Apple MPS not supported in v1.)
Environment detection (`--env auto`): Colab if `google.colab` imports or `COLAB_GPU` is set; AWS if IMDSv2 answers within 1 s or `AWS_EXECUTION_ENV` is set; otherwise `local`. This only picks defaults (destination, scratch dir, weights source); every default can be overridden.

### 4.3 Worker sizing (`--workers auto`)
- **GPU**: per GPU, `N = min(floor(free_vram / 2.6 GB), floor(free_ram / 3.5 GB), cores - post_workers_reserved)`, then an optional **calibration**: run `bench` (10 verses at N=1, 2, 3...) and keep the smallest N within 5% of the best throughput. Cached in `~/.cache/pipeline/calib-<gpu_name>.json`. On a T4 this yields N=1 (measured); on A10G/L4/L40S it must be measured, not assumed.
- **Multi-GPU box**: one worker group per visible GPU (`CUDA_VISIBLE_DEVICES` per process).
- **CPU only**: workers = `min(cores, floor(free_ram / 3.5 GB))` (a render needs ~3.4 GB; project constraint: never exceed RAM). Expect this to be slow; it exists so local/Colab-CPU runs work.
- **Post workers**: `max(1, cores - render_workers)`; alignment RAM ~1.2 GB each is included in the RAM check. Never start a worker set that would exceed total RAM.
- Deliberately **not** in v1: batching several verses inside one process (rejected by the owner in favour of multi-process; it remains a future option if bigger GPUs show no multi-process gain).

### 4.4 Scale-out on spot (the main speed lever)
Run K independent instances, each `--shard i/K`, started manually by the owner (D16; no launcher in v1). Shards are disjoint, results are immutable segments with unique names, so there is nothing to coordinate. Interrupted instances are simply restarted with the same arguments; the planner skips what is already published. A launcher (`aws_spot.sh`, zone fallback, AMI bake) is a possible later addition.
Spot interruption: poll IMDS `spot/instance-action` every 5 s; on notice, stop taking jobs, seal and publish the open segment (needs < 2 min), exit 0.

### 4.5 GPU options (decide by cost per 1000 verses, measured)
ap-south-1 prices from the AWS Pricing API / spot price history on 2026-11-09 (3-day spot average). Speeds other than the T4 are **unmeasured**; the "needs speed-up of" column is the break-even versus g4dn.xlarge on cost per verse.

| Instance | GPU | VRAM | vCPU / RAM | Spot $/h | On-demand $/h | Break-even speed-up vs T4 (spot) |
|---|---|---|---|---|---|---|
| g4dn.xlarge | T4 | 16 GB | 4 / 16 GB | 0.262 | 0.579 | 1.0x (baseline) |
| g4dn.2xlarge | T4 | 16 GB | 8 / 32 GB | 0.377 | 0.828 | only helps if CPU post-processing is the bottleneck |
| g6.xlarge | L4 | 24 GB | 4 / 16 GB | 0.467 | 0.966 | 1.8x |
| g5.xlarge | A10G | 24 GB | 4 / 16 GB | 0.559 | 1.208 | 2.1x |
| g6e.xlarge | L40S | 48 GB | 4 / 32 GB | 1.752 | 2.235 | 6.7x |

Reference cost, T4 spot, render only, step 10: 100,000 verses x 7.07 s = ~196 GPU-hours = **~$51** (lower bound; excludes load, alignment, MP3, retries). With K=10 instances: ~20 h wall clock. Hypothesis to test with `bench`: A10G/L4 have several times the FP32 throughput of a T4 (vendor spec sheets, unverified), so one of them may beat the T4 on cost per verse; the L40S probably does not.
Also testable (changes audio, so USER-CHECK): fp16 autocast on the DiT (T4 has no bf16).

## 5. Input

### 5.1 Canonical record: `JobRecord` (JSONL, one object per line; `.jsonl` or `.jsonl.zst`)
```json
{
  "schema": 1,
  "verse_id": "baala-001-001",
  "work": "ramayana",
  "book": "baala",
  "chapter": 1,
  "seq": 1,
  "text_variant": "critical_smith",
  "text_fallback": false,
  "padas": ["तपःस्वाध्यायनिरतं तपस्वी वाग्विदां वरम्", "नारदं परिपप्रच्छ वाल्मीकिर्मुनिपुंगवम्"],
  "meter": "anuṣṭubh",
  "render": {"steps": 10, "seed": 50, "voice": "voice_armA_ema_2026-06-11.pt"}
}
```
(Example padas are the `critical_smith` lines of `baala-001-001` from `test_data`; real corpus data, not invented.)
- Required: `schema`, `verse_id` (globally unique, stable, `[a-z0-9_-]+`), `padas` (list of non-empty strings, danda/double-danda stripped like `common.load_verses`).
- Optional: `work`, `book`, `chapter`, `seq` (used for shard grouping and ordering), `text_variant` and `text_fallback` (provenance; set by the adapter per D8, copied to the catalog), `meter` (a reference-bank clip name; default `anuṣṭubh`, overridable per run with `--meter`; record value wins over the run flag), `render` overrides (defaults come from `pipeline/defaults.yaml`: steps 10, seed 50, voice/vocoder above, speed 0.90, cfg 3.0, mp3_kbps 192).
- Derived by the planner: `text_sha256` (of the padas as given), `params_hash` (of all render parameters + engine version). Either changing invalidates the stored result.
- Unknown fields are kept in the catalog `extra` column, not rejected.

### 5.2 Adapters (all produce the record above)
| Source | Flag | Notes |
|---|---|---|
| JSONL | `--input path.jsonl[.zst]` or a glob | the native format |
| Text files | `--input-txt dir` | UTF-8, one verse per block separated by a blank line; first line `# id: <verse_id> [meter: <name>]`, following lines are padas. Hierarchy is read from the id or from `# work/book/chapter` headers. |
| Postgres | `--pg-dsn ... --pg-query file.sql` or `--pg-table epic_verses --pg-variant critical_smith` | query must return the JobRecord columns; streamed with a server-side cursor in chunks of 5,000. Reads only; never writes. |
| Repo test data | `--input-epic-json test_data/ramayan/unified` | reads `verse_NNN.json`. Variant rule (D8): `critical_smith`, else `vulgate_net`, else `vulgate_in`; sets `text_variant`/`text_fallback`. Files without a `text` key are skipped (not verses). Used for the existing 26,100-verse Ramayana set. |

### 5.3 Corpus storage options (future; not needed for Ramayana now, see D6)
Requirements inferred from the corpus: 100k+ verses, hierarchical ids (work/book/chapter/verse), several text variants per verse (the existing JSON already has critical, vulgate_net, vulgate_in, Gita Press OCR + alignments between them), essentially write-once and read-mostly, bulk sequential reads by the pipeline, point lookups by the app.

| Option | Pros | Cons | Fit |
|---|---|---|---|
| **PostgreSQL** (JSONB per verse; the app already has `epic_verses`/`epic_sargas`, 26,100 verses) | Already running and used by the app; queries by book/chapter/id; indexes; transactions; JSONB keeps all variants; easy export | Needs a server reachable from spot/Colab (network, credentials); less convenient to ship to Android | Best **source of truth** |
| **Sharded JSONL + zstd** (e.g. one file per book/chapter group, 5-50 MB each) | Trivial to write/diff/version in git or S3; streams fast; no server; works identically on AWS/Colab/local; is the pipeline's native input | No indexed lookups; updates mean rewriting a file | Best **exchange/run format** |
| **Parquet** (columnar, partitioned by work/book) | Compact, fast scans, typed schema, reads in DuckDB/pandas/Spark | Overkill for text-only rows; nested variants need care; not human-readable | Good if analytics matter; optional |
| **SQLite file** | One file, SQL, zero server, ships to Colab/Android | Single-writer; large rewrites; not for concurrent services | Good read-only release artifact |
| **MongoDB / DocumentDB** | Natural fit for nested variants JSON; flexible schema | Extra service to run/pay; the app already has Postgres; no clear gain | Only if you need heavy schema drift |
| **DynamoDB** | Serverless, scales, pay per use; point lookups fast | AWS-only (breaks Colab/local); poor ad-hoc queries; item size and key design constraints | Poor fit |
| **One big JSON/text file** | Simplest to hand over | Whole-file loads; no partial reads; painful to diff and update; breaks at 100k+ with variants | Avoid |

**Recommendation:** keep Postgres as the master (it already exists), and have a small export job write release snapshots as sharded `*.jsonl.zst` in the `JobRecord` format. The pipeline reads the snapshots (no DB credentials on spot/Colab, reproducible runs); direct Postgres reading remains available for convenience. Mahabharata text must be supplied by the owner, in the same record format; this pipeline will not generate or fetch verse text.

## 6. Output

### 6.1 Why not a folder per verse
A folder tree needs 2-3 objects per verse (audio + alignment + meta): 50-80k objects for Ramayana alone, 200-300k at 100k verses. S3 PUT/LIST overhead, Drive's per-file API limits and Android file-system costs make that slow to write, list and sync (this is already visible in the existing Colab flow, which writes `chant.wav` + `result.json` per verse). Zip needs a central directory read per access; tar is sequential. Hence **packed shards with an offset index**.

### 6.2 Store layout (one store per work; D20)
```
<dest>/<work>/                      e.g. s3://sloka-poc-audio-785703562757/pipeline/ramayana/
  manifest.json                     written by merge: schema version, notices, file list with sha256, counts per status, last merge time
  catalog.sqlite                    written by merge only: the index (~10-30 MB for 100k verses)
  segments/seg-<run>-<worker>-<seq>.{audio.pack,align.pack,wav.pack,idx.jsonl}   written by `run`, immutable
  shards/{audio,align}-<book>-<nnnn>.pack   written by `compact` (optional): ~256 MB packs, live blobs only
  runs/<run_id>/{metrics.json,progress.jsonl,failed.jsonl}   per-run logs (small)
```
`audio.pack` = MP3 files concatenated back to back; `align.pack` = alignment JSON documents concatenated (UTF-8); `wav.pack` = WAVs of `align_failed` verses only (D14), absent for segments with none. Catalog entries point at segment files until `compact` rewrites them into shards, so consumers handle both uniformly (a `files` table, see 6.4). Shards are grouped by `(work, book)` so a client can fetch one kanda.

Size estimate (from `mp3.py`: 192 kbps mono = 24 kB/s): a 10 s verse ~ 255 KB, so **Ramayana (26,100 verses) ~ 6.6 GB** at 192 kbps (96 kbps: ~3.3 GB; real durations vary, re-measure after the first run), 100k verses ~ 25 GB. Bitrate is configurable (`mp3_kbps`, D11); 96 kbps mono halves it. Alignment JSON size is unmeasured (expect a few KB per verse).

### 6.3 Write-time: segments, merge, compact
To survive spot interruptions without thousands of tiny files, workers write **segments**: sealed every `min(256 MB, 5 minutes)`, named `seg-<run_id>-<worker>-<seq>.*`. Segments are immutable. A segment is *published* only after its `idx.jsonl` (written last) is uploaded, so a half-written segment is invisible. Every idx line is a complete verse record: all catalog columns of 6.4, plus blob offsets inside that segment, plus `created_at`.
- **`merge`** (owner's local machine, D15): `merge --into <store> [--from <other store>]...` first copies segments missing from `<store>` out of every `--from` store (S3, Drive mount or local folder; names are unique so copying cannot clash), then rebuilds `catalog.sqlite` and `manifest.json` from all `idx.jsonl` files. It is the only writer of the catalog, so there are no races between instances.
- **Conflicts (D19)**: for each `verse_id` the entry with the greatest `created_at` wins (ties: higher segment name). Older entries stay in their segments (counted as `superseded` in the manifest) until compaction. An older `ok` entry is never replaced by a newer `failed` one: a `failed` entry only wins when no `ok` or `align_failed` entry exists (so a transient failure cannot hide good audio).
- **`compact`** (optional, local): copies only live (winning) blobs into final ~256 MB shards (byte copy, no re-encode), drops superseded blobs and the WAVs of verses that are now `ok`, rewrites the catalog, and deletes old segments only with `--delete-old` after `verify` passes.
- A store is consistent when `manifest.json` is newer than every segment in it; segments newer than the manifest are simply not yet merged.

### 6.4 `catalog.sqlite`
```sql
CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);   -- schema_version, pipeline_version, mp3_kbps, lead_ms, merged_at, notices
CREATE TABLE files(file_id INTEGER PRIMARY KEY, kind TEXT, path TEXT, bytes INTEGER, sha256 TEXT);  -- kind: audio|align|wav; path relative to the store root (segment or shard)
CREATE TABLE verses(
  verse_id TEXT PRIMARY KEY, work TEXT, book TEXT, chapter INTEGER, seq INTEGER,
  status TEXT,                       -- ok | align_failed | failed
  error TEXT,                        -- failed: e.g. no_text, render_error, ...; align_failed: last alignment error
  text_variant TEXT, text_fallback INTEGER,    -- D8: variant actually rendered; 1 when not critical_smith
  duration_s REAL,                   -- includes the MP3 lead-in and tail
  audio_file INTEGER, audio_off INTEGER, audio_len INTEGER,    -- NULL when failed
  align_file INTEGER, align_off INTEGER, align_len INTEGER,    -- NULL when align_failed or failed
  wav_file INTEGER, wav_off INTEGER, wav_len INTEGER,          -- only align_failed (D14)
  syllables INTEGER, text_sha256 TEXT, params_hash TEXT,
  steps INTEGER, seed INTEGER, voice TEXT, meter TEXT, mp3_kbps INTEGER,
  run_id TEXT, created_at TEXT, superseded_count INTEGER, extra TEXT);
CREATE INDEX verses_order ON verses(work, book, chapter, seq);
CREATE INDEX verses_status ON verses(status);
```
Rules: offsets/lengths are bytes into the named file; `audio_len` bytes starting at `audio_off` are a complete, standalone MP3. One row per `verse_id` (the winner, D19). Alignment documents keep the **existing app schema** (`audio_duration`, `lines[].words[].{text,slp1,start,end,syllables[]}`), already shifted by `LEAD_MS` so times match the MP3, so the existing player code needs no change. `align_failed` verses have audio but no alignment: the player falls back to line-level timing.

### 6.5 How consumers read it
- **Web server**: open `catalog.sqlite`, look up `verse_id`, then either read `[off, off+len)` from the local file named by `audio_file` (segment or shard) or issue an HTTP `Range: bytes=off-(off+len-1)` request to S3/CloudFront; stream it as `audio/mpeg`. No shard needs to be downloaded whole.
- **Android**: copy `catalog.sqlite` plus the files (shards after `compact`) for the books needed to local storage; `RandomAccessFile`/`FileChannel` at `off` for `len` bytes feeds a custom ExoPlayer `DataSource` (or `MediaDataSource`); alignment JSON is read the same way. SQLite is native on Android. Shard downloads can be resumed and verified with `sha256` in `manifest.json`.
- **Verification**: `pipeline verify <store>` checks every offset/length, MP3 headers, JSON parse, sha256s, and that every selected input verse has a catalog row with status `ok`, `align_failed` or `failed` (with `error`).

## 7. Destinations and scratch space
`--dest` takes a path, `s3://bucket/prefix`, or `gdrive:` (resolved to the mounted Drive folder) and names the **work store** (6.2). Auto (`--env auto`): AWS -> `s3://sloka-poc-audio-785703562757/pipeline/ramayana/` (D21; override bucket/prefix), Colab -> `/content/drive/MyDrive/sloka_pipeline/ramayana/`, local -> `./pipeline_out/ramayana/`. Because Colab and AWS write to different stores, `merge --from` (6.3) is how they become one catalog.
- All heavy work happens on **local scratch** (instance NVMe `/mnt/data`, Colab `/content`, local temp); only sealed immutable files are copied to the destination. Never append to files on Drive or S3.
- S3 uses the instance role (no keys in files), multipart upload, checksum verification; an upload failure retries with backoff and never deletes the scratch copy.
- Drive writes only through the Colab mount; Drive's per-file API limits are why the output is packed.
- Weights: AWS from `s3://sloka-poc-audio-785703562757/setup/EdgeSanskrit-TTS` (3.0 GiB), otherwise HF `prathoshap/vagdhenu` (public, no token) or the local repo copy; fetched to scratch once per instance by `pipeline bootstrap`, order S3 -> HF/GitHub with retries and sha256 check (D26). The bucket holds copies of third-party weights: keep it private and mind their licences (plan.md R4).

## 8. CLI
```
python -m pipeline run      --input ... [--dest <store>] [--env auto|aws|colab|local]
                            [--book baala,ayodhya] [--chapters 1-10] [--ids a,b | --ids-file f]
                            [--only missing|align_failed|failed] [--force]
                            [--shard i/K] [--device auto|cuda|cpu] [--workers auto|N]
                            [--steps 10] [--seed 50] [--meter anuṣṭubh] [--mp3-kbps 192]
                            [--limit N] [--keep-wav] [--run-id ID] [--dry-run]
python -m pipeline bench    [--workers 1,2,3] [--verses 10]     # calibration + timings for this GPU, writes metrics
python -m pipeline merge    --into <store> [--from <store>]...  # copy segments, rebuild catalog.sqlite + manifest.json (local machine)
python -m pipeline compact  <store> [--delete-old]              # optional: live blobs -> final shards, drop superseded
python -m pipeline verify   <store>
python -m pipeline bootstrap                                    # weights + deps check on this machine
```
- `--only` needs the store's state: it reads `catalog.sqlite` if present plus any `idx.jsonl` newer than it. `missing` = selected verses with no row, `failed`/`align_failed` = rows with that status. Filters combine with AND; `--ids` is an explicit list. Seed fixed 50 (D18) but still overridable for experiments (changes `params_hash`).
- `--dry-run` prints the selection and counts and exits. A rerun after a crash needs no `--resume` flag: skipping done verses is the default.
- `--shard` applies after the filters, so `K` instances with the same filters cover the selection exactly once.
Config precedence: `pipeline/defaults.yaml` < record `render` fields < CLI flags (exception: `meter` — the record value wins over `--meter`, see 5.1). Every run writes `runs/<run_id>/metrics.json` (per-stage seconds, verses/s, per-worker utilisation, GPU memory peak, failures, status counts, fallback-text count, retry count) and a JSONL progress log.

## 9. Planned code layout (`pipeline/`)
`SPEC.md` (this), `defaults.yaml`, `__main__.py` (CLI), `schema.py` (JobRecord, validation), `adapters/{jsonl,txt,postgres,epic_json}.py`, `planner.py`, `hardware.py` (device/env/worker sizing), `workers.py` (render + post processes), `segments.py` (pack writer/reader), `merge.py`, `compact.py`, `catalog.py`, `stores/{local,s3,gdrive}.py`, `spot.py` (IMDS watcher), `bench.py`, `verify.py`, `tests/` (fake renderer returning the POC wav `POC/outputs/gita_2_47_default.wav`; no model in tests). No `launch/` in v1 (D16). It imports `backend.engine.*`; it does not import `backend.app` (no DB, no FastAPI).

## 10. Acceptance criteria
1. The same verses via the JSONL, text-dir, epic-json and Postgres adapters produce identical `JobRecord`s (same `text_sha256`), and identical catalogs (fake renderer). The epic-json adapter marks `vulgate_only` verses with `text_variant != critical_smith`, `text_fallback=1`, and skips files without `text`.
2. Kill -9 mid-run, rerun: no verse rendered twice, no corrupt or half-published segment visible, `merge` produces a complete catalog. Simulated spot notice seals and publishes within 30 s.
3. `verify` passes; a random 1% of verses extracted by offset play as complete MP3s and parse as alignment JSON.
4. `--shard i/K` for K=1..8 (with any filter) covers every selected verse exactly once.
5. Runs unchanged on a 4-vCPU CPU-only box (slow), a T4 box, and Colab; `bench` writes a calibration file.
5a. Selection: `--book`, `--chapters`, `--ids`, `--only missing|align_failed|failed` each select exactly the expected verses (fake store with known statuses); `--dry-run` writes nothing.
5b. Incremental/merge: two stores with an overlapping verse merge into one catalog where the newest entry wins, the older blob is still readable until `compact`, and a newer `failed` never replaces an older `ok`. `merge` is idempotent.
5c. Alignment failure: an injected alignment error is retried twice, then the verse is `align_failed` with audio, a WAV in the wav pack and no align entry; `--only align_failed` re-aligns it without rendering and the next merge/compact drops the WAV.
5d. Missing text: a verse with no usable variant is `failed` with `error=no_text` and is listed in `failed.jsonl`.
6. Real-hardware check (not CI): a 100-verse run on g4dn.xlarge reports throughput close to 1/7.07 verses/s per render process, and the post stage keeps up.
7. USER-CHECK (Claude cannot hear audio): audio quality at steps 10 for a sample across books; highlights match audible words; chosen MP3 bitrate acceptable on a phone; Android actually plays from offsets.

## 11. Risks and open questions
- **GPU-bound**: extra processes on a T4 add nothing (measured). Mitigated by calibration and scale-out across instances; bigger GPUs are unmeasured.
- **Alignment cost unknown**: MMS_FA on 4 vCPUs may become the bottleneck at 0.77 RTF rendering; `bench` must measure it before sizing instances (option: g4dn.2xlarge, or GPU alignment).
- **Spot capacity**: g4dn/g5/g6 spot may be unavailable in a zone; with no launcher (D16) the owner retries zones or uses on-demand by hand.
- **Colab**: sessions end; Drive quotas and slow tiny-file writes. Segments + Drive copy of sealed files address this. Colab GPU type varies (T4/L4/A100). Colab and AWS write to different stores and are combined only by `merge` on the local machine.
- **Text revisions**: changed text means a new `text_sha256`; the verse is re-rendered when selected and the newer entry wins (D19). Old blobs stay until `compact`.
- **Fallback text (D8)**: ~17% of the local sample is `vulgate_only`; those verses are spoken from a different edition than the critical text the Learn page may show. `text_fallback=1` lets consumers detect this. The `vulgate_net` ङ् (not anusvara) spelling before velars may need a `textprep` check (USER-CHECK on alignment).
- **Store growth**: superseded blobs and `align_failed` WAVs accumulate until `compact`; the manifest reports the superseded byte count.
- **POC bucket reuse (D21)**: the bucket also holds third-party weight copies under `setup/`; keep the whole bucket private. A dedicated bucket is a later option, not a v1 need.
- **Legal**: voice belongs to Prof. Prathosh (IISc); the "synthetic, not the speaker" notice must travel with the data (`manifest.json` `notices`). Meanings from `machine` origin are drafts and are not part of this pipeline's output.
Resolved in v0.2 (kept for traceability): O2 bitrate -> D11 (configurable, default 192; the release choice stays a USER-CHECK), O3 meter -> D10, O4 variant -> D8, O5 Colab flow -> D9.
- **[OPEN] O1** Long-term corpus storage (section 5.3). Not needed for Ramayana. Recommendation stays: Postgres master + sharded JSONL.zst snapshots.
- **[OPEN] O6** Mahabharata source file(s) and licence (to be supplied by the owner). Out of scope until then.
Also resolved: O7 fallback order is exactly `vulgate_net`, `vulgate_in` (never `vulgate_gitapress`; D23), O8 fallback is marked in the catalog only (D24).
- **[OPEN] P1** Alignment-time POC not yet done: see section 12. It blocks sizing of post workers and instances, not the code.

## 12. Pending POC: alignment and MP3 cost (P1)
Unmeasured today: MMS_FA alignment time per verse, MP3 encode time, and whether post-processing keeps up with 0.77 RTF rendering. Plan (run on the g4dn.xlarge, one model process at a time locally per CLAUDE.md; on EC2 the render and alignment may overlap):
1. **Input**: the 10 `baala-001-*` WAVs already in `POC/model_poc/results_s3/` plus the step-size WAVs (54 files, same verse), real `critical_smith` text from `test_data`. No new renders needed.
2. **Measure per verse**: `align.align` wall time and peak RSS on (a) CPU 1 thread, (b) CPU 4 threads, (c) CUDA; `validate` result; `wav_to_mp3` time; 3 repeats each, first call (model load) reported separately.
3. **Measure throughput**: N post workers = 1, 2, 3 on 4 vCPUs while one render process runs, to see whether render slows (CPU contention) or post lags (queue growth).
4. **Outputs**: `POC/model_poc/alignment_cost.md` with the table; decision rules: if CPU post time per verse <= 7 s with 1 worker, g4dn.xlarge is enough; else choose between 2 post workers, g4dn.2xlarge, or `--align-device cuda`. Record the result in D-list (new D25) and in §4.3.
5. **Alignment failure rate** on those ~64 WAVs is recorded too, to size the `align_failed` WAV pack and the retry cost.
Until P1 is done, defaults are `post_workers = max(1, cores - render_workers)` and `bench` is optional (a warning is printed when no calibration file exists); `run` is never blocked (D25).
