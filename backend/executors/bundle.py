"""Portable job bundles shared by the Drive and manual Colab executors and the Colab worker."""
from __future__ import annotations
import json, shutil, zipfile
from pathlib import Path, PurePosixPath

MAX_UNZIP_BYTES = 500 * 1024 * 1024


def make_bundle(spec: dict, dest) -> Path:
    dest = Path(dest); dest.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(spec["ref_wav"], dest / "ref.wav")
    out = dict(spec)
    out["ref_wav"] = "ref.wav"
    out["voice_ckpt"] = "models/" + Path(spec["voice_ckpt"]).name
    out["vocoder_ckpt"] = "models/" + Path(spec["vocoder_ckpt"]).name
    out["out_wav"] = "result/chant.wav"
    (dest / "spec.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return dest


def resolve_spec(bundle_dir, models_dir) -> dict:
    bundle_dir, models_dir = Path(bundle_dir), Path(models_dir)
    spec = json.loads((bundle_dir / "spec.json").read_text(encoding="utf-8"))
    for k in ("ref_wav", "voice_ckpt", "vocoder_ckpt", "out_wav"):
        v = spec[k]
        parts = PurePosixPath(v).parts
        if PurePosixPath(v).is_absolute() or ".." in parts:
            raise ValueError(f"unsafe path in spec.json: {k}={v!r}")
        spec[k] = str(models_dir / PurePosixPath(*parts[1:]) if parts[0] == "models" else bundle_dir / v)
    return spec


def zip_dir(src, zip_path, prefix: str = "") -> Path:
    src, zip_path = Path(src), Path(zip_path)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(src.rglob("*")):
            if p.is_file() and p.resolve() != zip_path.resolve():
                z.write(p, str(PurePosixPath(prefix) / p.relative_to(src).as_posix()))
    return zip_path


def check_zip(zip_path, max_bytes: int = MAX_UNZIP_BYTES) -> list[str]:
    """Return member names after validating them; raise ValueError if unsafe or too big."""
    try:
        z = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile as e:
        raise ValueError(f"not a valid zip: {e}")
    with z:
        total, names = 0, []
        for i in z.infolist():
            n = i.filename
            p = PurePosixPath(n.replace("\\", "/"))
            if p.is_absolute() or ".." in p.parts or (len(n) > 1 and n[1] == ":"):
                raise ValueError(f"unsafe path in zip: {n!r}")
            total += i.file_size
            if total > max_bytes:
                raise ValueError("zip too large when unpacked")
            names.append(n)
        return names


def unzip_safe(zip_path, dest, max_bytes: int = MAX_UNZIP_BYTES) -> Path:
    check_zip(zip_path, max_bytes)
    dest = Path(dest); dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(dest)
    return dest
