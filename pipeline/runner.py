"""`pipeline run`: orchestrates select -> render workers -> post workers -> segment writer -> store (SPEC 4, 8)."""
from __future__ import annotations

import json
import multiprocessing as mp
import os
import queue
import re
import shutil
import signal
import sys
import tempfile
import threading
import time
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

LAST_RUN: dict = {}        # summary of the most recent run() in this process (used by tests)
_VERSE_ID = re.compile(r"^[a-z0-9_-]+$")
_ID_PARTS = re.compile(r"^([a-z0-9_]+)-(\d+)-(\d+)$")


def _log(*a):
    print("[pipeline]", *a, file=sys.stderr, flush=True)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _new_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:4]


# --------------------------------------------------------------------------- argument handling
def build_cli(args) -> dict:
    """Only flags the user actually gave."""
    cli = {}
    for k in ("steps", "seed", "meter", "mp3_kbps"):
        v = getattr(args, k, None)
        if v is not None:
            cli[k] = v
    return cli


def build_selection(args):
    from .planner import Selection, parse_chapters, parse_shard
    ids = None
    if getattr(args, "ids", None):
        ids = {x.strip() for x in args.ids.split(",") if x.strip()}
    if getattr(args, "ids_file", None):
        lines = Path(args.ids_file).read_text(encoding="utf-8").split()
        ids = (ids or set()) | {x.strip() for x in lines if x.strip()}
    book = [b.strip() for b in args.book.split(",") if b.strip()] if getattr(args, "book", None) else None
    return Selection(book=book,
                     chapters=parse_chapters(args.chapters) if getattr(args, "chapters", None) else None,
                     ids=ids, only=getattr(args, "only", None), force=bool(getattr(args, "force", False)),
                     shard=parse_shard(args.shard) if getattr(args, "shard", None) else None,
                     limit=getattr(args, "limit", None))


def _scratch_root(args, env: str) -> tuple[Path, bool]:
    """(base dir, is_temp)."""
    if getattr(args, "scratch", None):
        return Path(args.scratch), False
    if env == "aws" and Path("/mnt/data").exists():
        return Path("/mnt/data/pipeline_scratch"), False
    if env == "kaggle":
        return Path("/kaggle/temp/pipeline_scratch"), False
    if env == "colab":
        return Path("/content/pipeline_scratch"), False
    return Path(tempfile.mkdtemp(prefix="pipeline_")), True


def _local_missing(dest: str) -> bool:
    return "://" not in dest and not dest.startswith("gdrive:") and not os.path.exists(dest)


def _invalid_entry(source, ident, message, run_id, work, params) -> dict:
    m = _ID_PARTS.match(ident)
    return {"verse_id": ident, "work": work, "book": m.group(1) if m else None,
            "chapter": int(m.group(2)) if m else None, "seq": int(m.group(3)) if m else None,
            "status": "failed", "error": message, "text_variant": None, "text_fallback": None, "duration_s": None,
            "syllables": None, "text_sha256": None, "params_hash": None, "steps": params.get("steps"),
            "seed": params.get("seed"), "voice": params.get("voice"), "meter": params.get("meter"),
            "mp3_kbps": params.get("mp3_kbps"), "run_id": run_id, "created_at": _now_iso(),
            "extra": {"source": str(source)}}


def _invalid_selected(ident: str, sel, state: dict) -> bool:
    """Whether a no-text/invalid verse should get a catalog row in this run."""
    from .planner import shard_of
    if ident in state:                          # never overwrite known rows; avoids a new row on every rerun
        return False
    if sel.only not in (None, "missing", "failed"):
        return False
    if sel.ids is not None and ident not in sel.ids:
        return False
    m = _ID_PARTS.match(ident)
    if sel.book and not (m and m.group(1) in sel.book):
        return False
    if sel.chapters is not None and not (m and int(m.group(2)) in sel.chapters):
        return False
    if sel.shard is not None:
        i, k = sel.shard
        if shard_of(ident, k) != i:
            return False
    return True


# --------------------------------------------------------------------------- threads
class Feeder(threading.Thread):
    def __init__(self, jobs, state, in_q, post_q, stop_evt, completed, max_inflight):
        super().__init__(daemon=True, name="feeder")
        self.jobs, self.state, self.in_q, self.post_q = jobs, state, in_q, post_q
        self.stop_evt, self.completed, self.max_inflight = stop_evt, completed, max_inflight
        self.submitted = 0
        self.done = False

    def run(self):
        try:
            for job in self.jobs:
                if self.stop_evt.is_set():
                    break
                if job.reuse == "wav":
                    while not self.stop_evt.is_set() and self.submitted - self.completed() >= self.max_inflight:
                        time.sleep(0.05)
                    if self.stop_evt.is_set():
                        break
                    self.post_q.put({"job": job, "wav": None, "old": self.state[job.record.verse_id],
                                     "render_s": 0.0, "worker": "reuse"})
                    self.submitted += 1
                else:
                    while not self.stop_evt.is_set():
                        try:
                            self.in_q.put(job, timeout=0.5)
                            self.submitted += 1
                            break
                        except queue.Full:
                            continue
        finally:
            self.done = True


class Collector(threading.Thread):
    """Owns the SegmentWriter: every add/seal happens on this thread."""

    def __init__(self, result_q, writer, run_dir: Path, run_id: str, store, t0: float):
        super().__init__(daemon=True, name="writer")
        self.result_q, self.writer, self.run_dir, self.run_id, self.store, self.t0 = result_q, writer, run_dir, run_id, store, t0
        self.completed = 0
        self.counts: Counter = Counter()
        self.stage: dict = defaultdict(float)
        self.busy: dict = defaultdict(float)
        self.fallback = 0
        self.retries = 0
        self.rendered = 0
        self.errors = 0
        self.finish = threading.Event()
        (run_dir / "runs").mkdir(parents=True, exist_ok=True)
        self.progress_path = run_dir / "runs" / "progress.jsonl"
        self.failed_path = run_dir / "runs" / "failed.jsonl"
        self.metrics_fn = None
        self._last_upload = time.time()

    def _tick(self):
        try:
            self.writer.maybe_seal()
        except Exception as e:
            self.errors += 1
            _log("seal/publish failed (will retry):", e)
        if self.store is not None and time.time() - self._last_upload > 60:
            self.upload_runs()

    def handle(self, msg: dict):
        e = msg["entry"]
        m = msg.get("metrics") or {}
        try:
            self.writer.add(e, msg.get("mp3"), msg.get("align"), msg.get("wav"))
        except Exception as ex:
            self.errors += 1
            _log(f"writer.add failed for {e['verse_id']}: {ex}")
            self.completed += 1                 # still counts, otherwise the run would wait forever
            return
        self.completed += 1
        self.counts[e["status"]] += 1
        if e.get("text_fallback"):
            self.fallback += 1
        if m.get("kind") == "post" and not m.get("reuse"):
            self.rendered += 1
        self.retries += max(0, int(m.get("align_attempts", 1)) - 1)
        for k in ("render_s", "align_s", "mp3_s"):
            self.stage[k] += float(m.get(k) or 0)
        if m.get("worker"):
            self.busy[m["worker"]] += float(m.get("render_s") or 0) + float(m.get("post_s") or 0)
        with open(self.progress_path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"t": round(time.time() - self.t0, 2), "verse_id": e["verse_id"], "status": e["status"],
                                "worker": m.get("worker"), "n": self.completed}, ensure_ascii=False) + "\n")
        if e["status"] in ("failed", "align_failed"):
            self.add_failed(e)
        _log(f"[{self.completed}] {e['verse_id']} {e['status']}" + (f" ({e['error'][:80]})" if e.get("error") else ""))

    def add_failed(self, e: dict):
        with open(self.failed_path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"verse_id": e["verse_id"], "status": e["status"], "error": e.get("error"),
                                "run_id": self.run_id}, ensure_ascii=False) + "\n")

    def upload_runs(self):
        self._last_upload = time.time()
        try:
            if self.metrics_fn:
                (self.run_dir / "runs" / "metrics.json").write_text(
                    json.dumps(self.metrics_fn(), indent=1, ensure_ascii=False), encoding="utf-8")
            for name in ("metrics.json", "progress.jsonl", "failed.jsonl"):
                p = self.run_dir / "runs" / name
                if p.exists():
                    self.store.put_bytes(f"runs/{self.run_id}/{name}", p.read_bytes())
        except Exception as ex:
            _log("run log upload failed:", ex)

    def run(self):
        while True:
            try:
                msg = self.result_q.get(timeout=0.5)
            except queue.Empty:
                self._tick()
                if self.finish.is_set():
                    break
                continue
            self.handle(msg)
            self._tick()


# --------------------------------------------------------------------------- run
def run(args) -> int:
    global LAST_RUN
    if getattr(args, "fake", False):
        os.environ["PIPELINE_FAKE"] = "1"
    from . import engine_io as E, hardware as H
    from .adapters import iter_records
    from .catalog import load_state
    from .planner import select, summarize
    from .schema import load_defaults
    from .stores import default_dest, open_store

    t0 = time.time()
    run_id = getattr(args, "run_id", None) or _new_run_id()
    env_req = getattr(args, "env", None)
    env = env_req if env_req and env_req != "auto" else H.detect_env()
    device = H.detect_device(getattr(args, "device", None))
    work = getattr(args, "work", None) or "ramayana"
    dest = getattr(args, "dest", None) or default_dest(env, work)
    defaults = load_defaults()
    cli = build_cli(args)
    sel = build_selection(args)
    dry = bool(getattr(args, "dry_run", False))
    _log(f"run {run_id} env={env} device={device} dest={dest}" + (" (dry-run)" if dry else ""))

    store = None if (dry and _local_missing(dest)) else open_store(dest)
    state = load_state(store) if store is not None else {}

    invalid: list = []
    total_in = [0]

    def counted():
        for r in iter_records(args, on_invalid=lambda source, ident, message: invalid.append((source, ident, message))):
            total_in[0] += 1
            yield r

    jobs = select(counted(), state, sel, defaults, cli)
    skipped_done = 0 if sel.force else sum(1 for v in state.values() if v.get("status") == "ok")
    summary = summarize(jobs, total_in[0], skipped_done)
    _log("plan:", json.dumps(summary, ensure_ascii=False, default=str))
    if invalid:
        _log(f"{len(invalid)} invalid/no-text record(s)")
    if dry:
        print(json.dumps({"summary": summary, "invalid": len(invalid)}, ensure_ascii=False, default=str))
        LAST_RUN = {"run_id": run_id, "dry_run": True, "planned": len(jobs), "summary": summary}
        return 0

    inv_rows, inv_other = [], []
    for source, ident, message in invalid:
        # only verses with a real id and no usable text become catalog rows; other bad records (bad JSON,
        # bad fields: `ident` may be a line number or path) are listed in failed.jsonl only
        if message == "no_text" and ident and _VERSE_ID.match(str(ident)):
            if _invalid_selected(str(ident), sel, state):
                inv_rows.append(_invalid_entry(source, str(ident), "no_text", run_id, work, {**defaults, **cli}))
        else:
            inv_other.append({"verse_id": None, "status": "invalid", "error": f"{source} {ident}: {message}",
                              "run_id": run_id})
    # jobs: longest first (less tail idle time)
    jobs.sort(key=lambda j: -E.count_syllables(list(j.record.padas)))

    # --- sizing
    fake = E.is_fake()
    render_jobs = sum(1 for j in jobs if j.reuse is None)
    gpus = H.gpu_info() if device == "cuda" else []
    calib = H.load_calib(gpus[0]["name"]) if gpus else None
    if device == "cuda" and calib is None:
        _log("warning: no calibration file (run `python -m pipeline bench`); using the formula sizing")
    w = getattr(args, "workers", None)
    requested = int(w) if w not in (None, "auto") else None
    cores, ram = H.cpu_cores(), H.free_ram_gb()
    if fake:
        sizing = {"render_per_gpu": 1, "gpu_groups": 1, "render": requested or 1, "post": 2, "notes": []}
    else:
        sizing = H.size_workers(device, min((g["free_mb"] for g in gpus), default=15000), ram, cores, calib,
                                n_gpus=max(1, len(gpus)), requested=requested)
    for n in sizing["notes"]:
        _log(n)
    n_render = 0 if render_jobs == 0 else sizing["render"]
    n_post = sizing["post"] if jobs else 0
    if jobs:
        _log(f"workers: {n_render} render, {n_post} post (cores={cores}, free RAM={ram:.1f} GB)")

    base, is_temp = _scratch_root(args, env)
    run_dir = base / run_id
    (run_dir / "seg").mkdir(parents=True, exist_ok=True)
    keep_wav = bool(getattr(args, "keep_wav", False))

    from .segments import SegmentWriter
    writer = SegmentWriter(scratch_dir=str(run_dir / "seg"), run_id=run_id, worker="w0", store=store,
                           max_bytes=256 * 1024 * 1024, max_age_s=300)
    ctx = mp.get_context("spawn")
    in_q = ctx.Queue(maxsize=max(2, n_render * 2))
    post_q = ctx.Queue()
    result_q = ctx.Queue()
    stop_evt = threading.Event()
    notice = {"spot": False, "signal": False, "budget": False}

    def on_stop(why):
        def cb(*_a):
            notice[why] = True
            _log(f"{why} stop requested: no new jobs, sealing and publishing")
            stop_evt.set()
        return cb

    def on_budget():
        notice["budget"] = True
        _log("[budget] max-hours reached: no new jobs, sealing and publishing")
        stop_evt.set()

    budget_timer = None
    max_hours = getattr(args, "max_hours", None)
    if max_hours is not None:
        budget_timer = threading.Timer(max(0.0, max_hours * 3600.0 - (time.time() - t0)), on_budget)
        budget_timer.daemon = True
        budget_timer.start()

    old_sig = None
    if threading.current_thread() is threading.main_thread():
        old_sig = signal.signal(signal.SIGTERM, on_stop("signal"))
    watcher = None
    if env == "aws":
        from .spot import SpotWatcher
        watcher = SpotWatcher(on_stop("spot"))
        watcher.start()

    sampler = H.Sampler(interval=5.0, gpu=(device == "cuda"))
    sampler.start()
    collector = Collector(result_q, writer, run_dir, run_id, store, t0)
    submitted_extra = 0

    def metrics() -> dict:
        el = max(1e-6, time.time() - t0)
        return {"run_id": run_id, "env": env, "device": device, "dest": dest, "elapsed_s": round(el, 1),
                "planned": len(jobs), "invalid_rows": len(inv_rows), "completed": collector.completed,
                "verses_per_s": round(collector.completed / el, 4), "status_counts": dict(collector.counts),
                "fallback_text": collector.fallback, "align_retries": collector.retries,
                "stage_seconds": {k: round(v, 2) for k, v in collector.stage.items()},
                "worker_busy_s": {k: round(v, 2) for k, v in collector.busy.items()},
                "worker_utilisation": {k: round(v / el, 3) for k, v in collector.busy.items()},
                "workers": {"render": n_render, "post": n_post}, "resources": sampler.summary(),
                "stopped_early": stop_evt.is_set(), "spot_notice": notice["spot"], "budget_stop": notice["budget"], "writer_errors": collector.errors,
                "summary": summary}

    collector.metrics_fn = metrics
    collector.start()
    with open(collector.failed_path, "a", encoding="utf-8") as f:
        for row in inv_other:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    for row in inv_rows:                                  # no-text rows go through the same writer thread
        result_q.put({"type": "result", "entry": row, "mp3": None, "align": None, "wav": None,
                      "metrics": {"kind": "invalid"}})
        collector.add_failed(row)
        submitted_extra += 1

    from .workers import drain, post_worker, render_worker
    procs_r, procs_p = [], []
    exit_code = 0
    feeder = None
    try:
        if jobs:
            per_gpu = sizing["render_per_gpu"]
            for k in range(n_render):
                g = (k // per_gpu) % max(1, len(gpus)) if gpus else None
                gi = gpus[g]["index"] if gpus else None
                p = ctx.Process(target=render_worker, args=(f"r{k}", gi, device, in_q, post_q, result_q, str(run_dir), run_id),
                                daemon=True, name=f"render-{k}")
                p.start(); procs_r.append(p)
            threads = str(max(1, (cores - n_render) // max(1, n_post)))
            saved = {k: os.environ.get(k) for k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS")}
            if not fake:
                os.environ["OMP_NUM_THREADS"] = os.environ["MKL_NUM_THREADS"] = threads
            cfg = {"align_retries": int(defaults.get("align_retries", 2)), "keep_wav": keep_wav,
                   "align_device": getattr(args, "align_device", None) or "cpu"}
            for k in range(n_post):
                p = ctx.Process(target=post_worker, args=(f"p{k}", post_q, result_q, str(run_dir), run_id, cfg,
                                                          dest if store is not None else None),
                                daemon=True, name=f"post-{k}")
                p.start(); procs_p.append(p)
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
            feeder = Feeder(jobs, state, in_q, post_q, stop_evt, lambda: collector.completed - submitted_extra,
                            max_inflight=2 * (n_render + n_post) + 2)
            feeder.start()

        dropped = 0
        deadline = None
        while True:
            if feeder is None:
                if collector.completed >= submitted_extra:
                    break
            else:
                target = feeder.submitted - dropped + submitted_extra
                if stop_evt.is_set() and deadline is None:
                    feeder.join(timeout=5)
                    dropped = drain(in_q)
                    deadline = time.time() + 90
                    continue
                if feeder.done and collector.completed >= target:
                    break
                if deadline is not None and time.time() > deadline:
                    _log("drain deadline reached; sealing what is written")
                    exit_code = 1 if not (notice["spot"] or notice["signal"] or notice["budget"]) else 0
                    break
                dead_post = procs_p and not any(p.is_alive() for p in procs_p)
                dead_render = procs_r and not any(p.is_alive() for p in procs_r)
                if dead_post or dead_render:
                    _log("all post workers died" if dead_post else "all render workers died")
                    stop_evt.set()
                    exit_code = 1
                    break
            if not collector.is_alive():
                exit_code = 1
                break
            time.sleep(0.2)
    except KeyboardInterrupt:
        _log("interrupted: sealing what is written")
        stop_evt.set()
        exit_code = 130
    finally:
        stop_evt.set()
        for p in procs_r:
            try:
                in_q.put(None, timeout=1)
            except Exception:
                pass
        for _ in procs_p:
            try:
                post_q.put(None)
            except Exception:
                pass
        for p in procs_r + procs_p:
            p.join(timeout=15)
            if p.is_alive():
                p.terminate()
        collector.finish.set()
        collector.join(timeout=60)
        sampler.stop()
        if budget_timer:
            budget_timer.cancel()
        if watcher:
            watcher.stop()
        if old_sig is not None:
            signal.signal(signal.SIGTERM, old_sig)

    sealed_ok = True
    try:
        writer.seal()
        writer.close()
    except Exception as e:
        sealed_ok = False
        exit_code = 1
        _log(f"seal/publish FAILED, scratch kept at {run_dir}: {e}")
    if store is not None:
        collector.upload_runs()
    if collector.errors:
        exit_code = exit_code or 1
    LAST_RUN = {"run_id": run_id, "dry_run": False, "planned": len(jobs), "rendered": collector.rendered,
                "completed": collector.completed, "counts": dict(collector.counts), "invalid_rows": len(inv_rows),
                "exit": exit_code, "dest": dest, "stopped_early": stop_evt.is_set() and (notice["spot"] or notice["signal"] or notice["budget"]),
                "summary": summary}
    _log(f"done: {dict(collector.counts)} in {time.time() - t0:.0f}s (run {run_id})")
    if sealed_ok and not keep_wav:
        shutil.rmtree(run_dir, ignore_errors=True)
        if is_temp:
            shutil.rmtree(base, ignore_errors=True)
    elif keep_wav:
        _log(f"WAVs kept under {run_dir / 'wav'}")
    return exit_code
