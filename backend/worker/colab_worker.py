"""Colab worker. Drive mode: poll <drive-root>/jobs/*/READY. Manual mode: --bundle DIR.
Usage: python -m backend.worker.colab_worker --drive-root R --models-dir M [--once]
       python -m backend.worker.colab_worker --bundle DIR --models-dir M"""
from __future__ import annotations
import argparse, json, os, sys, time, traceback
from pathlib import Path
from backend.executors.bundle import resolve_spec


class JobCancelled(Exception): ...


def _write_json(p: Path, obj):
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, p)


def default_render_factory(device=None):
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


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--drive-root"); ap.add_argument("--models-dir", required=True)
    ap.add_argument("--bundle"); ap.add_argument("--once", action="store_true")
    ap.add_argument("--device", default=None); ap.add_argument("--poll", type=float, default=3.0)
    a = ap.parse_args(argv)
    render = default_render_factory(a.device)
    if a.bundle:
        run_bundle(Path(a.bundle), a.models_dir, render, status=False); print("DONE"); return
    if not a.drive_root: ap.error("--drive-root or --bundle required")
    (Path(a.drive_root) / "jobs").mkdir(parents=True, exist_ok=True)
    serve(a.drive_root, a.models_dir, render, a.once, a.poll)


if __name__ == "__main__":
    main()
