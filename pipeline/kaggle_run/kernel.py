"""Kaggle kernel script (STDLIB ONLY). Runs `python -m pipeline run` headless on a Kaggle GPU notebook.

Pushed by pipeline/kaggle_run/launch.py. Expects two attached datasets: the code dataset (contains pipeline/,
backend/ and config.json) and the verses dataset (contains *.jsonl). Secrets AWS_ACCESS_KEY_ID /
AWS_SECRET_ACCESS_KEY (optional AWS_DEFAULT_REGION) come from Kaggle Secrets. Secrets are never printed.
"""
import collections
import glob
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time

INPUT = "/kaggle/input"
WORKING = "/kaggle/working"
TEMP = "/kaggle/temp"
STATUS = os.path.join(WORKING, "status.json")
CODE_DIR = os.path.join(TEMP, "code")
BOOT_TARGET = os.path.join(TEMP, "EdgeSanskrit-TTS")
SCRATCH = os.path.join(TEMP, "pipeline_scratch")
SECRETS = ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY")
TAIL = collections.deque(maxlen=50)
STATE = {"started": None, "stages": [], "exit_code": None, "error": None}

# module to probe -> pip requirement. torch/torchaudio are never installed here (Kaggle provides them).
NEEDED = [
    ("boto3", "boto3"),
    ("huggingface_hub", "huggingface_hub"),
    ("numpy", "numpy"),
    ("scipy", "scipy"),
    ("soundfile", "soundfile"),
    ("librosa", "librosa"),
    ("safetensors", "safetensors"),
    ("vocos", "vocos"),
    ("x_transformers", "x-transformers"),
    ("indic_transliteration", "indic-transliteration"),
    ("pyarrow", "pyarrow<20"),
    ("f5_tts", "f5-tts @ git+https://github.com/ai4bharat/IndicF5.git@13f7c4d627cc10111aea8fe9c0039462cacacdc7"),
]


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())


def log(*a):
    print("[kernel]", *a, flush=True)


def write_status(final=False):
    data = dict(STATE, updated=now(), final=final, log_tail=list(TAIL))
    try:
        os.makedirs(WORKING, exist_ok=True)
        with open(STATUS, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1)
    except OSError as e:
        print("[kernel] cannot write status:", e, flush=True)


def fail(msg, code=2):
    log("FATAL:", msg)
    TAIL.append("FATAL: " + msg)
    STATE["error"] = msg
    STATE["exit_code"] = code
    write_status(final=True)
    sys.exit(code)


def stream(cmd, stage, env=None, cwd=None):
    """Run cmd, copy output to the log and to the tail buffer, record exit code. Returns the exit code."""
    log("$", " ".join(cmd))
    t0 = now()
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env, cwd=cwd,
                         errors="replace")
    n = 0
    for line in p.stdout:
        line = line.rstrip("\n")
        print(line, flush=True)
        TAIL.append(line[:500])
        n += 1
        if n % 200 == 0:
            write_status()
    rc = p.wait()
    STATE["stages"].append({"stage": stage, "start": t0, "end": now(), "exit_code": rc})
    write_status()
    return rc


def load_secrets():
    try:
        from kaggle_secrets import UserSecretsClient
    except Exception:
        # allow pre-set environment (e.g. a dry test); on Kaggle the import works
        if all(os.environ.get(k) for k in SECRETS):
            return
        fail("kaggle_secrets not importable and AWS keys not in environment")
    client = UserSecretsClient()
    missing = []
    for k in SECRETS:
        try:
            os.environ[k] = client.get_secret(k)
        except Exception:
            missing.append(k)
    if missing:
        fail("missing Kaggle Secrets: " + ", ".join(missing) +
             ". Add them in the notebook (Add-ons > Secrets) and attach them to this notebook.")
    try:
        os.environ["AWS_DEFAULT_REGION"] = client.get_secret("AWS_DEFAULT_REGION")
    except Exception:
        os.environ.setdefault("AWS_DEFAULT_REGION", "ap-south-1")
    log("secrets loaded:", ", ".join(SECRETS))


def check_gpu():
    if shutil.which("nvidia-smi") is None:
        fail("no GPU: nvidia-smi not found. Enable an accelerator (GPU T4 x2) in the notebook settings.")
    try:
        out = subprocess.check_output(["nvidia-smi", "-L"], text=True, timeout=30)
    except Exception as e:
        fail(f"nvidia-smi failed: {e}")
    if "GPU" not in out:
        fail("no GPU listed by nvidia-smi")
    log(out.strip())
    if shutil.which("ffmpeg") is None:
        log("WARNING: ffmpeg not found; MP3 encoding will fail")


def find_code():
    for d in sorted(glob.glob(os.path.join(INPUT, "*")) + glob.glob(os.path.join(INPUT, "*", "*"))):
        if os.path.isdir(os.path.join(d, "pipeline")) and os.path.isfile(os.path.join(d, "config.json")):
            return d
    fail("code dataset not found under /kaggle/input (need a dir with pipeline/ and config.json)")


def find_verses(code_dir):
    dirs = {}
    for p in glob.glob(os.path.join(INPUT, "**", "*.jsonl"), recursive=True):
        if not os.path.abspath(p).startswith(os.path.abspath(code_dir) + os.sep):
            dirs.setdefault(os.path.dirname(p), []).append(p)
    if not dirs:
        fail("no *.jsonl found under /kaggle/input (verses dataset not attached?)")
    d = sorted(dirs, key=lambda k: -len(dirs[k]))[0]
    return os.path.join(d, "*.jsonl"), sum(len(v) for v in dirs.values())


def pip_install():
    missing = [req for mod, req in NEEDED if importlib.util.find_spec(mod) is None]
    if not missing:
        log("all python deps present")
        return
    log("installing:", ", ".join(m.split(" @ ")[0] for m in missing))
    cons = os.path.join(TEMP, "constraints.txt")
    os.makedirs(TEMP, exist_ok=True)
    lines = []
    try:
        from importlib.metadata import version
        for pkg in ("torch", "torchaudio", "torchvision", "numpy"):
            try:
                lines.append(f"{pkg}=={version(pkg)}")
            except Exception:
                pass
    except Exception:
        pass
    with open(cons, "w") as f:
        f.write("\n".join(lines) + "\n")
    cmd = [sys.executable, "-m", "pip", "install", "-q", "-c", cons] + missing
    rc = stream(cmd, "pip")
    if rc != 0:
        fail(f"pip install failed (exit {rc}); is internet enabled for this notebook?", rc)


def small_metrics():
    out = {}
    for p in glob.glob(os.path.join(SCRATCH, "**", "metrics.json"), recursive=True):
        try:
            if os.path.getsize(p) < 200_000:
                with open(p, encoding="utf-8") as f:
                    out[os.path.relpath(p, SCRATCH)] = json.load(f)
        except Exception:
            pass
    if out:
        with open(os.path.join(WORKING, "metrics.json"), "w", encoding="utf-8") as f:
            json.dump(out, f)
        log("wrote /kaggle/working/metrics.json")


def main():
    STATE["started"] = now()
    write_status()
    check_gpu()
    load_secrets()
    code = find_code()
    with open(os.path.join(code, "config.json"), encoding="utf-8") as f:
        cfg = json.load(f)
    os.makedirs(TEMP, exist_ok=True)
    if os.path.exists(CODE_DIR):
        shutil.rmtree(CODE_DIR)
    shutil.copytree(code, CODE_DIR)           # /kaggle/input is read-only; pipeline may want to write pycache
    pattern, n_files = find_verses(code)
    log(f"code: {code}  verses: {pattern} ({n_files} file(s))")
    sys.path.insert(0, CODE_DIR)
    env = dict(os.environ)
    env["PYTHONPATH"] = CODE_DIR + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONUNBUFFERED"] = "1"
    pip_install()
    rc = stream([sys.executable, "-m", "pipeline", "bootstrap", "--target", BOOT_TARGET], "bootstrap", env, CODE_DIR)
    if rc != 0:
        fail(f"bootstrap failed (exit {rc})", rc)
    env["SS_VAGDHENU"] = os.path.join(BOOT_TARGET, "vagdhenu")
    env["SS_BIGVGAN"] = os.path.join(BOOT_TARGET, "BigVGAN")
    cmd = [sys.executable, "-m", "pipeline", "run", "--env", "kaggle", "--input", pattern]
    if cfg.get("dest"):
        cmd += ["--dest", str(cfg["dest"])]
    cmd += ["--max-hours", str(cfg.get("max_hours", 11))]
    cmd += [str(a) for a in cfg.get("run_args", [])]
    rc = stream(cmd, "run", env, CODE_DIR)
    STATE["exit_code"] = rc
    small_metrics()
    write_status(final=True)
    log("done, exit code", rc)
    return rc


if __name__ == "__main__":
    sys.exit(main())
