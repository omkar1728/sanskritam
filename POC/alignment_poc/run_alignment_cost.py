"""Alignment + MP3 cost POC (pipeline/SPEC.md section 12, item P1).

Measures, on EXISTING WAVs (no rendering):
  1. MMS_FA alignment wall time per verse and peak RSS for: cpu with 1 thread, cpu with N threads, cuda.
  2. validate() result and alignment success/failure per WAV (feeds the align_failed estimate).
  3. ffmpeg MP3 encode time at each bitrate (default 192 and 96 kbps).
  4. Contention: K parallel post processes over the same WAVs (wall time per verse, total throughput).

Inputs (text comes from the files, never typed here):
  - POC/model_poc/results_s3/ba-sarga1-2026-11-08/vagdhenu/baala-001-NNN.wav + verses_used.json (the padas they were rendered from)
  - POC/model_poc/results_s3/vagdhenu-stepsize-2026-11-09/audio/**/step_NN_rR.wav (all baala-001-001; padas from the same verses_used.json)

Run from the repo root, ONE model process at a time on the 6 GB dev box (alignment ~1.2 GB):
    PYTHONPATH=. uv run python POC/alignment_poc/run_alignment_cost.py --modes cpu1,cpu4
On the EC2 T4 box (15 GB RAM) add cuda and contention:
    PYTHONPATH=. python POC/alignment_poc/run_alignment_cost.py --modes cpu1,cpu4,cuda --contention 1,2,3
Then summarise:
    python POC/alignment_poc/summarize.py POC/alignment_poc/results/<run>.json
"""
from __future__ import annotations
import argparse, json, multiprocessing as mp, os, resource, subprocess, sys, tempfile, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RES = ROOT / "POC" / "model_poc" / "results_s3"
SARGA = RES / "ba-sarga1-2026-11-08"
STEPS = RES / "vagdhenu-stepsize-2026-11-09" / "audio"
OUT = Path(os.environ.get("POC_OUT", ROOT / "POC" / "alignment_poc" / "results"))
LEAD_MS, TAIL_S = 400, 0.3


def collect_inputs(max_steps_files: int) -> list[dict]:
    """[{id, wav, padas, source}]. Padas come from verses_used.json (the exact text each WAV was rendered from)."""
    verses = {v["id"]: v for v in json.loads((SARGA / "verses_used.json").read_text(encoding="utf-8"))}
    items = []
    for vid, v in verses.items():
        w = SARGA / "vagdhenu" / f"{vid}.wav"
        if w.exists():
            items.append({"id": vid, "wav": str(w), "padas": v["padas"], "source": "sarga1"})
    base = verses.get("baala-001-001")
    if base and STEPS.exists():
        for w in sorted(STEPS.rglob("step_*_r*.wav"))[:max_steps_files]:
            items.append({"id": f"baala-001-001/{w.stem}", "wav": str(w), "padas": base["padas"], "source": "steps"})
    return items


def rss_mb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0     # Linux: KiB


def encode_mp3(wav: str, mp3: str, kbps: int) -> float:
    t = time.time()
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", wav, "-af",
                    f"adelay={LEAD_MS},apad=pad_dur={TAIL_S},loudnorm=I=-18:TP=-1.5:LRA=7",
                    "-ar", "44100", "-ac", "1", "-b:a", f"{kbps}k", mp3], check=True)
    return time.time() - t


def align_one(item: dict, device: str) -> dict:
    """Same rules as backend/app/queue.py::_align, plus timing. Never raises."""
    from backend.engine import align as A
    from backend.engine.synth import syllable_counts
    t = time.time()
    rec = {"id": item["id"], "source": item["source"], "ok": False, "error": None, "soft": None}
    try:
        try:
            al = A.align(item["wav"], item["padas"], [p.split() for p in item["padas"]], device=device)
        except ValueError:
            al = A.align(item["wav"], item["padas"], device=device)
        errs = A.validate(al, syllable_counts(item["padas"]))
        soft = [e for e in errs if "syllables, expected" in e]
        errs = [e for e in errs if e not in soft]
        rec["soft"] = soft or None
        if errs:
            rec["error"] = "; ".join(errs[:3])
        else:
            rec["ok"] = True
    except Exception as e:                                   # record, never stop the POC
        rec["error"] = f"{type(e).__name__}: {e}"
    rec["align_s"] = round(time.time() - t, 3)
    return rec


def run_mode(items: list[dict], mode: str, repeats: int) -> dict:
    import torch
    from backend.engine import align as A
    A.unload()
    device = "cuda" if mode == "cuda" else "cpu"
    if mode.startswith("cpu"):
        torch.set_num_threads(int(mode[3:] or 1))
    if device == "cuda" and not torch.cuda.is_available():
        return {"mode": mode, "skipped": "cuda not available"}
    t = time.time()
    A._get_model(device)                                     # model load reported separately
    load_s = time.time() - t
    rows = []
    for r in range(repeats):
        for it in items:
            row = align_one(it, device); row["repeat"] = r + 1
            rows.append(row)
            print(f"[{mode}] {row['id']} r{r + 1} {row['align_s']}s ok={row['ok']}", file=sys.stderr, flush=True)
    A.unload()
    return {"mode": mode, "load_s": round(load_s, 2), "peak_rss_mb": round(rss_mb(), 0), "rows": rows}


def run_mp3(items: list[dict], kbps_list: list[int], repeats: int) -> dict:
    out = {}
    with tempfile.TemporaryDirectory() as td:
        for k in kbps_list:
            ts, sizes = [], []
            for r in range(repeats):
                for i, it in enumerate(items):
                    mp3 = os.path.join(td, f"{k}_{i}.mp3")
                    ts.append(encode_mp3(it["wav"], mp3, k)); sizes.append(os.path.getsize(mp3))
            out[str(k)] = {"mean_s": round(sum(ts) / len(ts), 3), "max_s": round(max(ts), 3),
                           "mean_bytes": round(sum(sizes) / len(sizes))}
    return out


def _contention_worker(args):
    items, device, threads = args
    import torch
    torch.set_num_threads(threads)
    from backend.engine import align as A
    A._get_model(device)
    t0 = time.time(); times = []
    for it in items:
        s = time.time(); align_one(it, device); times.append(time.time() - s)
    return {"wall_s": time.time() - t0, "per_verse_s": times, "rss_mb": rss_mb()}


def run_contention(items: list[dict], k: int, device: str, threads: int) -> dict:
    """k processes each aligning the same items. Needs ~1.2 GB RAM each: refuse on a small box unless --force."""
    ctx = mp.get_context("spawn")
    t = time.time()
    with ctx.Pool(k) as pool:
        res = pool.map(_contention_worker, [(items, device, threads)] * k)
    wall = time.time() - t
    n = k * len(items)
    return {"processes": k, "threads_each": threads, "device": device, "wall_s": round(wall, 2),
            "verses": n, "verses_per_s": round(n / wall, 3),
            "mean_per_verse_s": round(sum(sum(r["per_verse_s"]) for r in res) / n, 3),
            "max_rss_mb": round(max(r["rss_mb"] for r in res), 0)}


def free_ram_gb() -> float:
    for line in open("/proc/meminfo"):
        if line.startswith("MemAvailable"):
            return int(line.split()[1]) / 1048576
    return 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--modes", default="cpu1,cpu4", help="comma list of cpu<N-threads> and cuda")
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--step-files", type=int, default=12, help="how many step-size WAVs (all baala-001-001) to include")
    ap.add_argument("--mp3-kbps", default="192,96")
    ap.add_argument("--contention", default="", help="comma list of process counts, e.g. 1,2,3 (EC2 only)")
    ap.add_argument("--contention-threads", type=int, default=1)
    ap.add_argument("--contention-device", default="cpu")
    ap.add_argument("--force", action="store_true", help="allow contention runs when free RAM looks too small")
    ap.add_argument("--run-name", default=time.strftime("%Y%m%d-%H%M%S"))
    a = ap.parse_args()

    items = collect_inputs(a.step_files)
    if not items:
        sys.exit("no input WAVs found under POC/model_poc/results_s3 (pull them from S3 first)")
    result = {"run": a.run_name, "n_inputs": len(items), "cores": os.cpu_count(), "free_ram_gb_at_start": round(free_ram_gb(), 1),
              "modes": [], "mp3": None, "contention": []}
    for mode in [m for m in a.modes.split(",") if m]:
        result["modes"].append(run_mode(items, mode, a.repeats))
    result["mp3"] = run_mp3(items, [int(x) for x in a.mp3_kbps.split(",") if x], max(1, a.repeats - 1))
    for k in [int(x) for x in a.contention.split(",") if x]:
        need = 1.5 * k
        if free_ram_gb() < need and not a.force:
            result["contention"].append({"processes": k, "skipped": f"free RAM {free_ram_gb():.1f} GB < {need:.1f} GB (use --force)"})
            continue
        result["contention"].append(run_contention(items, k, a.contention_device, a.contention_threads))
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / f"{a.run_name}.json"
    p.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {p}", file=sys.stderr)


if __name__ == "__main__":
    main()
