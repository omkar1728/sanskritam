"""Colab worker. Drive mode: poll <drive-root>/jobs/*/READY. Manual mode: --bundle DIR.
Usage: python -m backend.worker.colab_worker --drive-root R --models-dir M [--once]
       python -m backend.worker.colab_worker --bundle DIR --models-dir M
       python -m backend.worker.colab_worker --batch DIR (--results DIR | --results-root DRIVE_ROOT) --models-dir M [--workers N]   (DIR = extracted batch.zip)"""
from __future__ import annotations
import argparse, json, os, signal, subprocess, sys, threading, time, traceback
from pathlib import Path
from backend.executors.bundle import resolve_spec, resolve_spec_dict


GB_PER_WORKER = 3.6          # measured system RAM per worker process on a real Colab run
STAGGER_MAX_S = 20.0         # max wait for a child's first output before starting the next
REPO_ROOT = Path(__file__).resolve().parents[2]


class JobCancelled(Exception): ...


def _write_json(p: Path, obj):
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, p)


def _test_hook_fake_render(spec: dict, progress):
    """TEST HOOK ONLY (SS_FAKE_RENDER=1): writes a stub wav, no torch/models."""
    progress(1, 2, "fake")
    Path(spec["out_wav"]).write_bytes(b"RIFF")
    return {"duration": 1.0, "pada_spans": [[0, 1.0]], "syllables": []}


def default_render_factory(device=None):
    if os.environ.get("SS_FAKE_RENDER") == "1": return _test_hook_fake_render
    engine = None
    def render(spec: dict, progress):
        nonlocal engine
        from backend.engine.synth import Engine, RenderSpec    # lazy: heavy imports
        engine = engine or Engine()                             # kept warm across jobs
        if device: spec = dict(spec, device=device)
        return engine.render(RenderSpec(**spec), progress)
    return render


def run_bundle(jd: Path, models_dir, render, status=True):
    """Render one bundle dir; writes result/ (and status.json if status). Raises on failure."""
    jd = Path(jd)
    def st(state, progress=0.0, message="", **kw):
        if status: _write_json(jd / "status.json", dict(state=state, progress=progress, message=message, **kw))
    st("running", 0.0, "starting")
    spec = resolve_spec(jd, models_dir)
    Path(spec["out_wav"]).parent.mkdir(parents=True, exist_ok=True)
    def progress(done, total, msg):
        if (jd / "CANCEL").exists(): raise JobCancelled()
        st("running", done / max(total, 1) * 0.98, msg); print(f"PROGRESS {done} {total} {msg}", flush=True)
    res = render(spec, progress)
    info = {"duration": res["duration"], "pada_spans": res.get("pada_spans", []), "syllables": res.get("syllables", [])}
    _write_json(jd / "result" / "result.json", info)
    return info


def process_job(jd: Path, models_dir, render):
    jd = Path(jd)
    try:
        info = run_bundle(jd, models_dir, render)
        _write_json(jd / "status.json", dict(state="done", progress=1.0, message="done"))
        (jd / "DONE").write_text("done")
        return info
    except JobCancelled:
        _write_json(jd / "status.json", dict(state="failed", progress=0, message="cancelled", error="cancelled"))
        (jd / "FAILED").write_text("cancelled")
    except Exception as e:
        traceback.print_exc()
        _write_json(jd / "status.json", dict(state="failed", progress=0, message="failed", error=f"{type(e).__name__}: {e}"[-2000:]))
        (jd / "FAILED").write_text(str(e))


def claim(jd: Path) -> bool:
    try:
        with open(jd / "CLAIMED", "x") as f: f.write(str(time.time()))
        return True
    except OSError:
        return False


def poll_once(root: Path, models_dir, render) -> int:
    n = 0
    for jd in sorted((Path(root) / "jobs").glob("*")):
        if (jd / "READY").exists() and not (jd / "CLAIMED").exists() and claim(jd):
            if (jd / "CANCEL").exists():
                _write_json(jd / "status.json", dict(state="failed", progress=0, message="cancelled", error="cancelled"))
                (jd / "FAILED").write_text("cancelled")
            else:
                print(f"[worker] job {jd.name}", flush=True)
                process_job(jd, models_dir, render)
            n += 1
    return n


def serve(root, models_dir, render, once=False, poll_s=3.0, stop=None):
    while not (stop and stop.is_set()):
        n = poll_once(Path(root), models_dir, render)
        if once and n: return
        time.sleep(poll_s if not once else poll_s)


def parse_shard(text: str) -> tuple[int, int]:
    try: i, n = (int(x) for x in str(text).split("/"))
    except ValueError: raise ValueError(f"bad shard {text!r}, expected i/N")
    if n < 1 or not 0 <= i < n: raise ValueError(f"bad shard {text!r}, expected 0 <= i < N")
    return i, n


def shard_jobs(jobs: list, shard: tuple[int, int] | None) -> list[tuple[int, dict]]:
    """[(global 1-based index, job)] owned by the shard; job at 0-based index k goes to shard k % N."""
    i, n = shard or (0, 1)
    return [(k + 1, j) for k, j in enumerate(jobs) if k % n == i]


def safe_rel(p, what="path") -> str:
    """Validate a POSIX path relative to the Drive root; raises ValueError if unsafe."""
    t = str(p or "")
    if (not t or "\\" in t or t.startswith("/") or ":" in t or "\x00" in t
            or any(part in ("", "..") for part in t.split("/"))):
        raise ValueError(f"unsafe {what}: {t!r}")
    return t


def load_layout(batch_dir, results_dir=None, results_root=None):
    """-> (jobs, {job_id: job_dir}, err_dir). Root mode uses result_dir/batch_dir from batch.json
    (all validated; ValueError rejects the whole batch); flat mode uses results_dir/<job_id>."""
    meta = json.loads((Path(batch_dir) / "batch.json").read_text(encoding="utf-8"))
    jobs = meta.get("jobs", [])
    if results_root:
        root = Path(results_root)
        err_dir = root / safe_rel(meta.get("batch_dir"), "batch_dir")
        dirs = {str(j["job_id"]): root / safe_rel(j.get("result_dir"), "result_dir") for j in jobs}
    else:
        err_dir = Path(results_dir)
        dirs = {str(j["job_id"]): err_dir / str(j["job_id"]) for j in jobs}
    return jobs, dirs, err_dir


def _done(jd: Path) -> bool:
    return (jd / "chant.wav").exists() and (jd / "result.json").exists()


def run_batch(batch_dir, results_dir, models_dir, render, shard=None, results_root=None) -> dict:
    """Render every job of batch_dir/batch.json. Flat mode: results_dir/<job_id>/. Root mode
    (results_root): <root>/<job.result_dir>/. Resumable (done = chant.wav and result.json; result.json
    is written last); per-job errors go to errors.json (errors.<i>.json when sharded) in results_dir, or
    <root>/<batch_dir> in root mode. shard=(i, N) renders only jobs with index % N == i.
    Returns {"ok", "skipped", "failed", "total"} (total = this shard's jobs)."""
    batch_dir = Path(batch_dir)
    all_jobs, dirs, err_dir = load_layout(batch_dir, results_dir, results_root)
    err_dir.mkdir(parents=True, exist_ok=True)
    mine = shard_jobs(all_jobs, shard)
    ep = err_dir / ("errors.json" if shard is None else f"errors.{shard[0]}.json")
    try: errors = json.loads(ep.read_text(encoding="utf-8")) if ep.exists() else {}
    except ValueError: errors = {}
    n, ok, skipped, failed = len(all_jobs), 0, 0, 0
    for i, job in mine:
        jid = str(job["job_id"]); jd = dirs[jid]
        if _done(jd):
            skipped += 1
            if errors.pop(jid, None) is not None: _write_json(ep, errors)
            print(f"[batch] {i}/{n} job {jid} skipped (already done)", flush=True); continue
        t0 = time.time()
        try:
            spec = resolve_spec_dict(job["spec"], batch_dir, models_dir)
            jd.mkdir(parents=True, exist_ok=True)
            part = jd / "chant.part.wav"
            part.unlink(missing_ok=True)
            spec["out_wav"] = str(part)
            def progress(done, total, msg, i=i):
                print(f"PROGRESS {done} {total} job {i}/{n}: {msg}", flush=True)
            res = render(spec, progress)
            info = {"duration": res["duration"], "pada_spans": res.get("pada_spans", []), "syllables": res.get("syllables", [])}
            if not part.exists(): raise RuntimeError("render produced no chant.wav")
            os.replace(part, jd / "chant.wav")          # atomic: no half wav under the final name
            _write_json(jd / "result.json", info)       # completion marker, written last
            ok += 1
            if errors.pop(jid, None) is not None: _write_json(ep, errors)
            print(f"[batch] {i}/{n} job {jid} ok {time.time() - t0:.1f}s", flush=True)
        except Exception as e:
            traceback.print_exc()
            failed += 1
            errors[jid] = f"{type(e).__name__}: {e}"[-2000:]
            _write_json(ep, errors)
            print(f"[batch] {i}/{n} job {jid} FAILED {time.time() - t0:.1f}s: {e}", flush=True)
    print(f"[batch] finished: ok={ok} skipped={skipped} failed={failed} total={len(mine)}", flush=True)
    return {"ok": ok, "skipped": skipped, "failed": failed, "total": len(mine)}


def merge_errors(results_dir, job_dirs=None) -> dict:
    """Merge errors.<i>.json into errors.json (jobs that now have results are dropped); shard files removed.
    job_dirs maps job_id -> dir (default results_dir/<job_id>). Writes errors.json only if there is
    something to say or it already existed."""
    results_dir = Path(results_dir)
    def load(p):
        try: return json.loads(p.read_text(encoding="utf-8"))
        except (ValueError, OSError): return {}
    ep = results_dir / "errors.json"
    shard_files = sorted(p for p in results_dir.glob("errors.*.json") if p.name.count(".") == 2 and p.name.split(".")[1].isdigit())
    merged = load(ep) if ep.exists() else {}
    for p in shard_files: merged.update(load(p))
    merged = {k: v for k, v in merged.items()
              if not _done(Path(job_dirs[k]) if job_dirs and k in job_dirs else results_dir / k)}
    if merged or ep.exists() or shard_files: _write_json(ep, merged)
    for p in shard_files: p.unlink(missing_ok=True)
    return merged


def _meminfo_available_gb():
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"): return int(line.split()[1]) / 1024 / 1024
    except (OSError, ValueError, IndexError): pass
    return None


def resource_warnings(workers: int, avail_gb=None, cpus=None, gb_per_worker=GB_PER_WORKER) -> list[str]:
    """Warnings (never blocking) when N workers likely exceed RAM or CPU count."""
    out = []
    need = workers * gb_per_worker
    if avail_gb is not None and need > avail_gb:
        out.append(f"WARNING: {workers} worker(s) need about {need:.1f} GB RAM ({gb_per_worker} GB each) "
                   f"but only {avail_gb:.1f} GB is available; the runtime may run out of memory and crash.")
    if cpus is not None and workers > cpus:
        out.append(f"WARNING: {workers} workers but only {cpus} CPU(s); extra workers will not speed things up.")
    return out


def run_parallel(batch_dir, results_dir, models_dir, device, workers, stagger_s=STAGGER_MAX_S, results_root=None) -> dict:
    """Spawn `workers` shard children, stream their output prefixed [w<i>], merge errors. Returns
    {"crashed": [shard idx...], "ok": n_done_in_results, "failed": n_errors}."""
    for w in resource_warnings(workers, _meminfo_available_gb(), os.cpu_count()): print(w, flush=True)
    jobs, dirs, err_dir = load_layout(batch_dir, results_dir, results_root)     # validates; ValueError rejects
    err_dir.mkdir(parents=True, exist_ok=True)
    where = ["--results-root", str(results_root)] if results_root else ["--results", str(results_dir)]
    procs = []
    def pump(i, proc, first):
        for line in proc.stdout:
            print(f"[w{i}] {line.rstrip()}", flush=True); first.set()
        first.set()
    try:
        for i in range(workers):
            cmd = [sys.executable, "-u", "-m", "backend.worker.colab_worker", "--batch", str(batch_dir),
                   *where, "--models-dir", str(models_dir), "--shard", f"{i}/{workers}"]
            if device: cmd += ["--device", device]
            proc = subprocess.Popen(cmd, cwd=REPO_ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            first = threading.Event()
            t = threading.Thread(target=pump, args=(i, proc, first), daemon=True); t.start()
            procs.append((i, proc, t))
            if i < workers - 1:
                print(f"[parent] started worker {i}; waiting for its first output before starting the next", flush=True)
                first.wait(stagger_s)
        crashed = []
        for i, proc, t in procs:
            rc = proc.wait(); t.join(5)
            if rc != 0: crashed.append(i); print(f"[parent] worker {i} crashed (exit code {rc})", flush=True)
    except BaseException:
        for _, proc, _ in procs:
            if proc.poll() is None: proc.terminate()
        for _, proc, _ in procs:
            try: proc.wait(10)
            except subprocess.TimeoutExpired: proc.kill()
        merge_errors(err_dir, dirs)
        raise
    errs = merge_errors(err_dir, dirs)
    done = sum(1 for j in jobs if _done(dirs[str(j["job_id"])]))
    print(f"[batch] finished: done={done} failed={len(errs)} total={len(jobs)} workers={workers}", flush=True)
    return {"crashed": crashed, "ok": done, "failed": len(errs)}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--drive-root"); ap.add_argument("--models-dir", required=True)
    ap.add_argument("--bundle"); ap.add_argument("--batch"); ap.add_argument("--results"); ap.add_argument("--results-root")
    ap.add_argument("--workers", type=int, default=1); ap.add_argument("--shard")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--device", default=None); ap.add_argument("--poll", type=float, default=3.0)
    a = ap.parse_args(argv)
    if a.workers < 1: ap.error("--workers must be >= 1")
    if a.batch:
        if not (a.results or a.results_root): ap.error("--results or --results-root required with --batch")
        root = a.results_root
        shard = None
        if a.shard:
            try: shard = parse_shard(a.shard)
            except ValueError as e: ap.error(str(e))
        elif a.workers > 1:
            signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
            r = run_parallel(a.batch, a.results, a.models_dir, a.device, a.workers, results_root=root)
            print("DONE")
            if r["crashed"]: sys.exit(1)
            return
        run_batch(Path(a.batch), Path(a.results or root), a.models_dir, default_render_factory(a.device), shard, results_root=root)
        if shard is None: print("DONE")
        return
    render = default_render_factory(a.device)
    if a.bundle:
        run_bundle(Path(a.bundle), a.models_dir, render, status=False); print("DONE"); return
    if not a.drive_root: ap.error("--drive-root or --bundle required")
    (Path(a.drive_root) / "jobs").mkdir(parents=True, exist_ok=True)
    serve(a.drive_root, a.models_dir, render, a.once, a.poll)


if __name__ == "__main__":
    main()
