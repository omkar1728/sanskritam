"""`pipeline bootstrap`: put the Vagdhenu weights/code in place and check the machine (SPEC 7, D26).

Order: S3 copy (setup/EdgeSanskrit-TTS) first, then HF prathoshap/vagdhenu + GitHub sources. Retries everywhere.
Nothing is ever installed automatically; missing tools are only reported. No token file is read or printed.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BUCKET = "sloka-poc-audio-785703562757"
S3_PREFIX = "setup/EdgeSanskrit-TTS/"
HF_REPO = "prathoshap/vagdhenu"
MODEL_FILES = ["voice_armA_ema_2026-06-11.pt", "voice_steer_ema_2026-06-17.pt",
               "voc_bigvgan_EMA_2026-06-11.pth", "vocab.txt"]
GIT_VAGDHENU = "https://github.com/prathoshap/vagdhenu"
GIT_BIGVGAN = "https://github.com/NVIDIA/BigVGAN"
RETRIES = 3


def _log(*a):
    print("[bootstrap]", *a, file=sys.stderr, flush=True)


def required_paths(target: Path) -> list[Path]:
    return ([target / "vagdhenu" / "models" / f for f in MODEL_FILES]
            + [target / "vagdhenu" / "src" / "reference_bank" / "bank.json",
               target / "BigVGAN" / "configs" / "bigvgan_v2_24khz_100band_256x.json"])


def missing_files(target: Path) -> list[Path]:
    return [p for p in required_paths(target) if not p.exists() or p.stat().st_size == 0]


def _retry(fn, what: str, tries: int = RETRIES):
    last = None
    for i in range(tries):
        try:
            return fn()
        except Exception as e:
            last = e
            _log(f"{what} failed (attempt {i + 1}/{tries}): {e}")
            time.sleep(min(30, 2 ** (i + 1)))
    raise RuntimeError(f"{what} failed after {tries} attempts: {last}")


# --------------------------------------------------------------------------- source 1: S3
def fetch_s3(target: Path, bucket: str, prefix: str = S3_PREFIX) -> None:
    import boto3                                    # credentials: instance role / environment, never read from files here
    s3 = boto3.client("s3")
    objs = []
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
        objs += [o for o in page.get("Contents", []) if not o["Key"].endswith("/")]
    if not objs:
        raise RuntimeError(f"nothing under s3://{bucket}/{prefix}")
    _log(f"s3://{bucket}/{prefix}: {len(objs)} files, {sum(o['Size'] for o in objs) / 1e9:.2f} GB")
    for o in objs:
        rel = o["Key"][len(prefix):]
        dst = target / rel
        if dst.exists() and dst.stat().st_size == o["Size"]:
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        part = dst.with_name(dst.name + ".part")

        def _get():
            s3.download_file(bucket, o["Key"], str(part))
            if part.stat().st_size != o["Size"]:
                raise IOError(f"size mismatch for {rel}: {part.stat().st_size} != {o['Size']}")
            os.replace(part, dst)
        _retry(_get, f"download {rel}")
        _log("got", rel)


# --------------------------------------------------------------------------- source 2: HF + GitHub
def fetch_hf(target: Path) -> None:
    from huggingface_hub import HfApi, hf_hub_download
    models = target / "vagdhenu" / "models"
    models.mkdir(parents=True, exist_ok=True)
    remote = _retry(lambda: HfApi().list_repo_files(HF_REPO), "list HF repo")
    for name in MODEL_FILES:
        dst = models / name
        if dst.exists() and dst.stat().st_size > 0:
            continue
        match = [f for f in remote if f.split("/")[-1] == name]
        if not match:
            raise RuntimeError(f"{name} not found in HF repo {HF_REPO}")
        with tempfile.TemporaryDirectory(prefix="hf_dl_", dir=str(target.parent)) as tmp:
            p = _retry(lambda: hf_hub_download(HF_REPO, match[0], local_dir=tmp), f"HF download {name}")
            shutil.move(p, dst)
        _log("got", name)


def _git_clone(url: str, dest: Path) -> None:
    if shutil.which("git") is None:
        raise RuntimeError("git not found")
    if dest.exists():
        shutil.rmtree(dest)
    _retry(lambda: subprocess.run(["git", "clone", "--depth", "1", url, str(dest)], check=True,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=900), f"git clone {url}")


def fetch_git(target: Path) -> None:
    src_dst = target / "vagdhenu" / "src"
    if not (src_dst / "reference_bank" / "bank.json").exists():
        with tempfile.TemporaryDirectory(prefix="vagdhenu_git_", dir=str(target.parent)) as tmp:
            _git_clone(GIT_VAGDHENU, Path(tmp) / "repo")
            if src_dst.exists():
                shutil.rmtree(src_dst)
            shutil.copytree(Path(tmp) / "repo" / "src", src_dst)
        _log("got vagdhenu src")
    bg = target / "BigVGAN"
    if not (bg / "configs" / "bigvgan_v2_24khz_100band_256x.json").exists():
        _git_clone(GIT_BIGVGAN, bg)
        shutil.rmtree(bg / ".git", ignore_errors=True)
        _log("got BigVGAN")


# --------------------------------------------------------------------------- machine checks
def check_machine() -> list[str]:
    problems = []
    if shutil.which("ffmpeg") is None:
        problems.append("ffmpeg not found (apt install ffmpeg)")
    else:
        _log("ffmpeg ok")
    if shutil.which("nvidia-smi") is None:
        problems.append("nvidia-smi not found: no NVIDIA driver (CPU only runs will be slow)")
    else:
        try:
            v = subprocess.check_output(["nvidia-smi", "--query-gpu=name,driver_version", "--format=csv,noheader"],
                                        text=True, timeout=10).strip()
            _log("nvidia:", v)
        except Exception as e:
            problems.append(f"nvidia-smi failed: {e}")
    try:
        out = subprocess.check_output(
            [sys.executable, "-I", "-c",
             "import torch;print(torch.__version__, torch.version.cuda, torch.cuda.is_available())"],
            text=True, timeout=180, stderr=subprocess.DEVNULL).strip()
        _log("torch:", out)
        if out.endswith("False") and shutil.which("nvidia-smi"):
            problems.append("torch has no usable CUDA (CPU build installed? install the CUDA build of torch)")
    except Exception:
        problems.append("torch not importable in this Python")
    if shutil.which("git") is None:
        problems.append("git not found (needed only for the HF/GitHub source)")
    return problems


def bootstrap(args) -> int:
    target = Path(getattr(args, "target", None) or ROOT / "EdgeSanskrit-TTS")
    bucket = getattr(args, "bucket", None) or os.environ.get("PIPELINE_BUCKET", DEFAULT_BUCKET)
    source = getattr(args, "source", None) or "auto"
    target.mkdir(parents=True, exist_ok=True)
    miss = missing_files(target)
    if miss and source in ("auto", "s3"):
        try:
            fetch_s3(target, bucket)
        except Exception as e:
            _log(f"S3 source unavailable: {e}")
        miss = missing_files(target)
    if miss and source in ("auto", "hf"):
        try:
            fetch_hf(target)
            fetch_git(target)
        except Exception as e:
            _log(f"HF/GitHub source failed: {e}")
        miss = missing_files(target)
    problems = check_machine()
    if miss:
        print("MISSING files:", *[f"  {p}" for p in miss], sep="\n", file=sys.stderr)
    else:
        _log(f"weights and code complete under {target}")
        if target.resolve() != (ROOT / "EdgeSanskrit-TTS").resolve():
            _log(f"non-default target: export SS_VAGDHENU={target / 'vagdhenu'} SS_BIGVGAN={target / 'BigVGAN'}")
    for p in problems:
        print("MISSING/PROBLEM:", p, file=sys.stderr)
    return 1 if (miss or any("ffmpeg" in p for p in problems)) else 0
