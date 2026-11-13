#!/usr/bin/env python3
"""Device-side launcher for the Kaggle headless run (stdlib + the `kaggle` CLI, run via subprocess).

  python -m pipeline.kaggle_run.launch push --user KAGGLE_USER --jsonl ramayana.jsonl [--dry-run]
  python -m pipeline.kaggle_run.launch status --user KAGGLE_USER
  python -m pipeline.kaggle_run.launch output --user KAGGLE_USER --out DIR
"""
from __future__ import annotations

import argparse
import importlib.util
import io
import json
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DEST = "s3://sloka-poc-audio-785703562757/pipeline/ramayana/"
SLUG_RE = re.compile(r"[a-z0-9-]{3,40}")
# Never copied into staging, at any depth.
EXCLUDE_NAMES = {"__pycache__", "tests", ".env", ".git", "EdgeSanskrit-TTS", "kaggle_run", ".venv", "storage"}
EXCLUDE_SUFFIX = (".pyc", ".pt", ".pth", ".ckpt", ".safetensors", ".wav", ".mp3", ".pem", ".key", ".db", ".sqlite",
                  ".zst", ".jsonl")
EXCLUDE_SUBSTR = ("secret", "credential", ".env")
NOTE = ("Machine shape: the kernel metadata only requests enable_gpu; Kaggle's default GPU is 'T4 x2'. "
        "If the CLI supports it, pass --accelerator (see `kaggle kernels push -h`); otherwise pick it in the "
        "notebook UI (Session options > Accelerator). Unverified against the current CLI.")


def _ignore(dirpath, names):
    d = Path(dirpath)
    out = []
    for n in names:
        low = n.lower()
        if n in EXCLUDE_NAMES or low.endswith(EXCLUDE_SUFFIX) or any(s in low for s in EXCLUDE_SUBSTR):
            out.append(n)
        elif d.name in ("input", "output") and d.parent.name == "pipeline" and n.lower() != "readme.md":
            out.append(n)                 # keep the folder, drop its contents (real corpus / results)
    return out


def validate(files) -> bool:
    spec = importlib.util.spec_from_file_location("validate_input", ROOT / "pipeline" / "tools" / "validate_input.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = mod.main([str(f) for f in files])
    print(buf.getvalue(), end="")
    return rc == 0


def _write_json(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def build_staging(stage: Path, user: str, slug: str, jsonls, dest: str, max_hours: float, run_args: list[str]):
    """Create stage/{code,verses,kernel}. Returns the three folders."""
    code, verses, kernel = stage / "code", stage / "verses", stage / "kernel"
    shutil.copytree(ROOT / "pipeline", code / "pipeline", ignore=_ignore)
    (code / "backend").mkdir(parents=True)
    for rel in ("__init__.py", "app/__init__.py", "app/config.py"):
        (code / "backend" / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / "backend" / rel, code / "backend" / rel)
    shutil.copytree(ROOT / "backend" / "engine", code / "backend" / "engine", ignore=_ignore)
    _write_json(code / "config.json", {"dest": dest, "max_hours": max_hours, "run_args": run_args})
    lic = [{"name": "CC0-1.0"}]
    _write_json(code / "dataset-metadata.json",
                {"title": f"{slug}-code", "id": f"{user}/{slug}-code", "licenses": lic})
    verses.mkdir(parents=True)
    for f in jsonls:
        shutil.copy2(f, verses / Path(f).name)
    _write_json(verses / "dataset-metadata.json",
                {"title": f"{slug}-verses", "id": f"{user}/{slug}-verses", "licenses": lic})
    kernel.mkdir(parents=True)
    shutil.copy2(Path(__file__).with_name("kernel.py"), kernel / "kernel.py")
    _write_json(kernel / "kernel-metadata.json", {
        "id": f"{user}/{slug}", "title": slug, "code_file": "kernel.py", "language": "python",
        "kernel_type": "script", "is_private": True, "enable_gpu": True, "enable_internet": True,
        "dataset_sources": [f"{user}/{slug}-code", f"{user}/{slug}-verses"],
        "competition_sources": [], "kernel_sources": [],
    })
    return code, verses, kernel


def tree(root: Path) -> str:
    lines = []
    for p in sorted(root.rglob("*")):
        if p.is_file():
            lines.append(f"  {p.relative_to(root)}  ({p.stat().st_size} B)")
    return "\n".join(lines)


def kaggle(args, check=False, capture=False):
    if shutil.which("kaggle") is None:
        raise SystemExit("kaggle CLI not found: pip install kaggle, then put the API token in ~/.kaggle/kaggle.json")
    return subprocess.run(["kaggle", *args], text=True, capture_output=capture, check=check)


def dataset_exists(ref: str) -> bool:
    r = kaggle(["datasets", "status", ref], capture=True)
    return r.returncode == 0 and "ready" in (r.stdout or "").lower()


def wait_ready(ref: str, timeout=900) -> None:
    t0 = time.time()
    while time.time() - t0 < timeout:
        r = kaggle(["datasets", "status", ref], capture=True)
        if r.returncode == 0 and "ready" in (r.stdout or "").lower():
            return
        time.sleep(15)
    raise SystemExit(f"dataset {ref} not ready after {timeout}s")


def cmd_push(a) -> int:
    if not SLUG_RE.fullmatch(a.slug):
        print("bad --slug (lowercase letters, digits, hyphens, 3-40 chars)")
        return 2
    files = [Path(f) for f in a.jsonl]
    for f in files:
        if not f.is_file():
            print(f"not a file: {f}")
            return 2
    if not validate(files):
        print("ABORT: input validation failed, nothing pushed")
        return 1
    run_args = shlex.split(a.run_args or "")
    keep = a.keep_staging or a.dry_run
    stage = Path(tempfile.mkdtemp(prefix="kaggle_stage_"))
    try:
        code, verses, kernel = build_staging(stage, a.user, a.slug, files, a.dest, a.max_hours, run_args)
        print(f"staging: {stage}")
        print(tree(stage))
        push = ["kernels", "push", "-p", str(kernel)]
        if a.accelerator:
            push += ["--accelerator", a.accelerator]
        steps = []
        for name, folder in (("code", code), ("verses", verses)):
            ref = f"{a.user}/{a.slug}-{name}"
            steps.append((name, ref, folder))
        print("\ncommands:")
        for name, ref, folder in steps:
            print(f"  kaggle datasets status {ref}   # decides create vs version")
            print(f"  kaggle datasets create -p {folder} --dir-mode zip      # first time")
            print(f"  kaggle datasets version -p {folder} -m 'update' --dir-mode zip   # later")
        print("  kaggle " + " ".join(push))
        print("\n" + NOTE)
        if a.dry_run:
            print("\ndry run: no kaggle command was run")
            return 0
        for name, ref, folder in steps:
            if dataset_exists(ref):
                r = kaggle(["datasets", "version", "-p", str(folder), "-m", "update", "--dir-mode", "zip"])
            else:
                r = kaggle(["datasets", "create", "-p", str(folder), "--dir-mode", "zip"])
            if r.returncode:
                print(f"ABORT: dataset {ref} failed")
                return r.returncode
        for _, ref, _ in steps:
            wait_ready(ref)
        r = kaggle(push)
        if r.returncode:
            return r.returncode
        print(f"""
NEXT STEPS
 1. Open https://www.kaggle.com/code/{a.user}/{a.slug} > Edit > Add-ons > Secrets: add AWS_ACCESS_KEY_ID and
    AWS_SECRET_ACCESS_KEY (optional AWS_DEFAULT_REGION), tick "attached" for this notebook. The CLI cannot set them.
 2. The account must be phone-verified for GPU + internet. Check Session options: accelerator GPU T4 x2, internet on.
 3. Secrets are read at run time, so after adding them re-run: `python -m pipeline.kaggle_run.launch push ...` again
    (a new version starts a fresh run) or use "Save Version > Save & Run All (Commit)" in the editor.
 4. Poll: python -m pipeline.kaggle_run.launch status --user {a.user} --slug {a.slug}
 5. Fetch: python -m pipeline.kaggle_run.launch output --user {a.user} --slug {a.slug} --out kaggle_out
    (audio is in S3 under {a.dest}; then `python -m pipeline merge --into <store> --from {a.dest}`)""")
        return 0
    finally:
        if not keep:
            shutil.rmtree(stage, ignore_errors=True)


def cmd_status(a) -> int:
    return kaggle(["kernels", "status", f"{a.user}/{a.slug}"]).returncode


def cmd_output(a) -> int:
    Path(a.out).mkdir(parents=True, exist_ok=True)
    return kaggle(["kernels", "output", f"{a.user}/{a.slug}", "-p", a.out]).returncode


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="launch", description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("push")
    p.add_argument("--user", required=True)
    p.add_argument("--jsonl", nargs="+", required=True)
    p.add_argument("--dest", default=DEFAULT_DEST)
    p.add_argument("--max-hours", type=float, default=11)
    p.add_argument("--slug", default="sloka-pipeline")
    p.add_argument("--run-args", default="", help='extra `pipeline run` flags, e.g. "--chapters 1-10"')
    p.add_argument("--accelerator", default=None, help="passed to `kaggle kernels push --accelerator` if given")
    p.add_argument("--keep-staging", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(fn=cmd_push)
    for name, fn in (("status", cmd_status), ("output", cmd_output)):
        q = sub.add_parser(name)
        q.add_argument("--user", required=True)
        q.add_argument("--slug", default="sloka-pipeline")
        if name == "output":
            q.add_argument("--out", required=True)
        q.set_defaults(fn=fn)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
