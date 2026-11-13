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
import shlex
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

# ---- EDIT THESE IN THE NOTEBOOK (no dataset change needed) ----------------------------------------------
# Arguments passed to `python -m pipeline run`. Examples: "--limit 100 --steps 11 --workers 3",
# "--book baala --chapters 1-10 --steps 11", "" (all verses, pipeline defaults).
# None = use run_args from config.json in the code dataset.
RUN_ARGS = "--limit 100 --steps 11 --workers 3"
MAX_HOURS = None        # None = use config.json (default 11)
# ---------------------------------------------------------------------------------------------------------
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
    # f5-tts runtime deps from IndicF5's setup.py, minus its "numpy<=1.26.4" pin (Kaggle's numpy is 2.x and is
    # held by the constraints file); f5-tts itself is installed with --no-deps below.
    ("accelerate", "accelerate>=0.33.0"),
    ("cached_path", "cached_path"),
    ("click", "click"),
    ("datasets", "datasets"),
    ("ema_pytorch", "ema-pytorch>=0.5.2"),
    ("hydra", "hydra-core>=1.3.0"),
    ("jieba", "jieba"),
    ("matplotlib", "matplotlib"),
    ("pydub", "pydub"),
    ("audioop", "audioop-lts; python_version>='3.13'"),
    ("pypinyin", "pypinyin"),
    ("tomli", "tomli"),
    ("torchdiffeq", "torchdiffeq"),
    ("tqdm", "tqdm>=4.65.0"),
    ("transformers", "transformers"),
    ("wandb", "wandb"),
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


def diagnose_network():
    """Log (never fail) whether the run has internet and what proxy/env hints exist. No secret values."""
    import socket
    import urllib.request
    for host in ("pypi.org", "s3.ap-south-1.amazonaws.com", "www.kaggle.com"):
        try:
            socket.create_connection((host, 443), timeout=8).close()
            log(f"net: {host}:443 reachable")
        except Exception as e:
            log(f"net: {host}:443 FAILED {type(e).__name__}: {str(e)[:120]}")
    try:
        with urllib.request.urlopen("https://pypi.org/simple/", timeout=10) as r:
            log("net: https GET pypi status", r.status)
    except Exception as e:
        log(f"net: https GET pypi FAILED {type(e).__name__}: {str(e)[:120]}")
    for k in ("KAGGLE_URL_BASE", "KAGGLE_USER_SECRETS_TOKEN", "KAGGLE_KERNEL_RUN_TYPE", "KAGGLE_IS_COMPETITION_RERUN",
              "HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "KAGGLE_DATA_PROXY_URL"):
        v = os.environ.get(k)
        log(f"env {k}:", "set" if v else "unset", (v if k in ("KAGGLE_KERNEL_RUN_TYPE", "KAGGLE_URL_BASE") and v else ""))


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
        except Exception as e:
            log(f"get_secret({k}) failed: {type(e).__name__}: {str(e)[:300]}")
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
    base_depth = INPUT.rstrip("/").count("/")
    for root, dirs, files in os.walk(INPUT):
        if root.count("/") - base_depth >= 6:
            dirs[:] = []
            continue
        if "pipeline" in dirs and "config.json" in files:
            return root
    # not found: show what is mounted so the cause is visible in the log
    log("listing of", INPUT, "(depth 4):")
    for root, dirs, files in os.walk(INPUT):
        depth = root.count("/") - base_depth
        if depth >= 4:
            dirs[:] = []
        log("  ", root, "dirs=", sorted(dirs)[:8], "files=", sorted(files)[:5])
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
    f5 = [m for m in missing if m.startswith("f5-tts")]
    others = [m for m in missing if not m.startswith("f5-tts")]
    steps = []
    if others:
        steps.append(("pip", [sys.executable, "-m", "pip", "install", "-c", cons] + others))
    if f5:
        steps.append(("pip-f5", [sys.executable, "-m", "pip", "install", "--no-deps"] + f5))
    for stage, cmd in steps:
        rc = stream(cmd, stage)
        if rc != 0:
            fail(f"{stage} install failed (exit {rc}); see the log tail (is internet enabled for this notebook?)", rc)


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
    diagnose_network()
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
    cmd += ["--max-hours", str(MAX_HOURS if MAX_HOURS is not None else cfg.get("max_hours", 11))]
    if RUN_ARGS is not None:
        extra = shlex.split(RUN_ARGS)
        log("run args from notebook constant RUN_ARGS:", extra)
    else:
        extra = [str(a) for a in cfg.get("run_args", [])]
        log("run args from config.json:", extra)
    cmd += extra
    rc = stream(cmd, "run", env, CODE_DIR)
    STATE["exit_code"] = rc
    small_metrics()
    write_status(final=True)
    log("done, exit code", rc)
    return rc


if __name__ == "__main__":
    sys.exit(main())
