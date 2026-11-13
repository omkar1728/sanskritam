"""`pipeline bench`: render throughput per worker count (calibration, SPEC 4.3) and optional align/MP3 cost (SPEC 12).

Never run by tests. Render mode writes ~/.cache/pipeline/calib-<gpu>.json; align mode writes a markdown table.
"""
from __future__ import annotations

import json
import multiprocessing as mp
import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = ROOT / "test_data" / "ramayan" / "unified" / "baala" / "sarga_001"
VARIANTS = ("critical_smith", "vulgate_net", "vulgate_in")


def _log(*a):
    print("[bench]", *a, file=sys.stderr, flush=True)


def _fixture_verses(n: int) -> list[dict]:
    """First n verses of Bala sarga 1 from test_data (text read from the files, never typed here)."""
    out = []
    for i in range(1, n + 1):
        f = FIXTURE_DIR / f"verse_{i:03d}.json"
        if not f.exists():
            break
        d = json.loads(f.read_text(encoding="utf-8"))
        for key in VARIANTS:
            lines = (d.get("text", {}).get(key) or {}).get("lines")
            if lines:
                out.append({"verse_id": d["id"], "padas": [l.strip().rstrip("।॥|").strip() for l in lines]})
                break
    if not out:
        raise SystemExit(f"no fixture verses under {FIXTURE_DIR}; pass --input")
    return out


def _load_verses(args, n: int) -> list[dict]:
    if getattr(args, "input", None) or getattr(args, "input_txt", None) or getattr(args, "input_epic_json", None) \
            or getattr(args, "pg_dsn", None):
        from .adapters import iter_records
        out = []
        for r in iter_records(args, on_invalid=lambda *a: None):
            out.append({"verse_id": r.verse_id, "padas": list(r.padas)})
            if len(out) >= n:
                break
        return out
    return _fixture_verses(n)


# --------------------------------------------------------------------------- render bench
def _bench_proc(wid, verses, params, device, gpu_index, ready_q, go_evt, done_q, scratch):
    if device == "cuda" and gpu_index is not None:
        os.environ["CUDA_VISIBLE_DEVICES"] = str(gpu_index)
    from . import engine_io as E
    from types import SimpleNamespace
    eng = E.make_engine()
    rec = lambda v: SimpleNamespace(padas=v["padas"], verse_id=v["verse_id"])
    wavp = str(Path(scratch) / f"bench-{wid}.wav")
    try:
        eng.render(E.build_render_spec(params, rec(verses[0]), wavp, device))      # warm-up incl. load, not measured
        ready_q.put((wid, None))
        go_evt.wait()
        times = []
        for v in verses:
            t = time.time()
            res = eng.render(E.build_render_spec(params, rec(v), wavp, device))
            times.append((time.time() - t, float(res["duration"])))
            for m in res.get("mels") or []:
                Path(m).unlink(missing_ok=True)
        done_q.put((wid, times, None))
    except Exception as e:
        ready_q.put((wid, repr(e)))
        done_q.put((wid, [], repr(e)))
    finally:
        Path(wavp).unlink(missing_ok=True)


def pick_best(throughput: dict[int, float], tol: float = 0.05) -> int:
    """Smallest worker count whose throughput is within 5% of the best."""
    best = max(throughput.values())
    return min(n for n, v in throughput.items() if v >= best * (1 - tol))


def bench_render(args) -> dict:
    from . import engine_io as E, hardware as H
    from .schema import load_defaults
    device = H.detect_device(getattr(args, "device", None))
    gpus = H.gpu_info() if device == "cuda" else []
    gpu_name = gpus[0]["name"] if gpus else None
    n_verses = int(getattr(args, "verses", None) or 10)
    counts = [int(x) for x in (getattr(args, "workers", None) or "1,2,3").split(",") if x.strip()]
    verses = _load_verses(args, n_verses)
    params = dict(load_defaults())
    for k in ("steps", "seed", "meter", "mp3_kbps"):
        if getattr(args, k, None) is not None:
            params[k] = getattr(args, k)
    ctx = mp.get_context("spawn")
    scratch = tempfile.mkdtemp(prefix="pipeline_bench_")
    rows, throughput = [], {}
    for n in counts:
        _log(f"N={n}: starting {n} process(es), {len(verses)} verses each (warm-up first)")
        ready_q, done_q, go = ctx.Queue(), ctx.Queue(), ctx.Event()
        procs = [ctx.Process(target=_bench_proc, args=(f"b{i}", verses, params, device,
                                                       gpus[0]["index"] if gpus else None, ready_q, go, done_q, scratch),
                             daemon=True) for i in range(n)]
        for p in procs:
            p.start()
        errs = [ready_q.get()[1] for _ in procs]
        if any(errs):
            for p in procs:
                p.terminate()
            _log("worker failed during warm-up:", [e for e in errs if e])
            break
        samp = H.Sampler(0.5, gpu=(device == "cuda")); samp.start()
        t0 = time.time(); go.set()
        results = [done_q.get() for _ in procs]
        wall = time.time() - t0
        samp.stop(); samp.join(timeout=2)
        for p in procs:
            p.join(timeout=30)
        times = [t for _, ts, _ in results for t in ts]
        total = len(times)
        thr = total / wall if wall > 0 else 0.0
        throughput[n] = thr
        row = {"workers": n, "verses": total, "wall_s": round(wall, 2), "verses_per_s": round(thr, 4),
               "mean_verse_s": round(sum(t for t, _ in times) / max(1, total), 2),
               "mean_audio_s": round(sum(a for _, a in times) / max(1, total), 2), **samp.summary()}
        rows.append(row)
        _log(row)
    out = {"created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "device": device,
           "gpu_name": gpu_name, "steps": params.get("steps"), "verses_per_process": len(verses), "rows": rows,
           "fake": E.is_fake()}
    if throughput:
        out["best_workers"] = pick_best(throughput)
        out["throughput"] = {str(k): round(v, 4) for k, v in throughput.items()}
        if gpu_name and not E.is_fake():
            p = H.calib_path(gpu_name)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
            _log(f"calibration written: {p} (best_workers={out['best_workers']})")
        else:
            _log("no GPU name / fake mode: calibration file not written")
    out_dir = Path(getattr(args, "out_dir", None) or ROOT / "POC" / "model_poc")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "bench_render.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    md = ["| workers | verses | wall s | verses/s | mean verse s | gpu util mean % | gpu mem peak MiB | sys cpu mean % | RAM peak GB |",
          "|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        md.append(f"| {r['workers']} | {r['verses']} | {r['wall_s']} | {r['verses_per_s']} | {r['mean_verse_s']} | "
                  f"{r['gpu_util_mean']} | {r['gpu_mem_peak_mib']} | {r['sys_cpu_mean']} | {r['ram_used_peak_gb']} |")
    (out_dir / "bench_render.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    return out


# --------------------------------------------------------------------------- align / mp3 bench (SPEC 12)
def _peak_rss_gb() -> float:
    try:
        for line in Path("/proc/self/status").read_text().splitlines():
            if line.startswith("VmHWM"):
                return int(line.split()[1]) / 1048576
    except Exception:
        pass
    return 0.0


def bench_align(args) -> dict:
    """Times align (per config), validate and MP3 encode on existing WAVs. One model process at a time."""
    from . import engine_io as E
    wav_dir = Path(args.wav_dir)
    wavs = sorted(wav_dir.rglob("*.wav"))[: int(getattr(args, "verses", None) or 10) * 6]
    if not wavs:
        raise SystemExit(f"no wav files under {wav_dir}")
    verses = _load_verses(args, 20)
    by_id = {v["verse_id"]: v["padas"] for v in verses}
    default_padas = verses[0]["padas"]

    def padas_for(w: Path):
        for vid, p in by_id.items():
            if vid in w.stem or vid in w.parent.name:
                return p
        return default_padas

    from backend.engine import align as A
    import torch
    repeats = 3
    threads = [int(x) for x in (getattr(args, "threads", None) or "1,4").split(",")]
    configs = [("cpu", t) for t in threads]
    if (getattr(args, "align_device", None) or "cpu") == "cuda" and torch.cuda.is_available():
        configs.append(("cuda", 0))
    rows = []
    for dev, th in configs:
        A.unload()
        if dev == "cpu":
            torch.set_num_threads(th)
        t = time.time()
        A._get_model(dev)
        load_s = time.time() - t
        _log(f"config {dev} threads={th}: model load {load_s:.1f}s")
        times, fails = [], 0
        for w in wavs:
            pd = padas_for(w)
            for r in range(repeats):
                t = time.time()
                al, err = E.align_with_retries(str(w), pd, retries=0, device=dev)
                times.append(time.time() - t)
                if r == 0 and al is None:
                    fails += 1
        times.sort()
        rows.append({"config": f"{dev} x{th}" if dev == "cpu" else "cuda", "wavs": len(wavs), "load_s": round(load_s, 1),
                     "align_mean_s": round(sum(times) / len(times), 2), "align_p95_s": round(times[int(len(times) * 0.95) - 1], 2),
                     "failures": fails, "rss_peak_gb": round(_peak_rss_gb(), 2)})
        _log(rows[-1])
    mp3_times = []
    with tempfile.TemporaryDirectory(prefix="pipeline_bench_mp3_") as d:
        for w in wavs[:10]:
            for _ in range(repeats):
                t = time.time()
                E.encode_mp3(str(w), str(Path(d) / "x.mp3"), 192)
                mp3_times.append(time.time() - t)
    mp3_mean = sum(mp3_times) / max(1, len(mp3_times))
    out_dir = Path(getattr(args, "out_dir", None) or ROOT / "POC" / "model_poc")
    out_dir.mkdir(parents=True, exist_ok=True)
    md = ["# Alignment and MP3 cost (bench --align)", "",
          f"WAVs: {len(wavs)} from `{wav_dir}`; {repeats} repeats each; first call (model load) reported separately.", "",
          "| config | wavs | model load s | align mean s | align p95 s | failures (of wavs) | peak RSS GB |",
          "|---|---|---|---|---|---|---|"]
    for r in rows:
        md.append(f"| {r['config']} | {r['wavs']} | {r['load_s']} | {r['align_mean_s']} | {r['align_p95_s']} | "
                  f"{r['failures']} | {r['rss_peak_gb']} |")
    md += ["", f"MP3 encode (192 kbps): mean {mp3_mean:.2f} s per file ({len(mp3_times)} runs).", "",
           "Decision rule (SPEC 12): CPU post time per verse <= 7 s with 1 worker means g4dn.xlarge is enough."]
    (out_dir / "alignment_cost.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    (out_dir / "alignment_cost.json").write_text(json.dumps({"rows": rows, "mp3_mean_s": mp3_mean}, indent=1), encoding="utf-8")
    _log(f"wrote {out_dir / 'alignment_cost.md'}")
    return {"rows": rows, "mp3_mean_s": mp3_mean}


def bench(args) -> int:
    if getattr(args, "fake", False):
        os.environ["PIPELINE_FAKE"] = "1"
    if getattr(args, "align", False):
        if not getattr(args, "wav_dir", None):
            raise SystemExit("--align needs --wav-dir")
        bench_align(args)
    else:
        bench_render(args)
    return 0
