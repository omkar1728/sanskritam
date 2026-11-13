from __future__ import annotations

from pathlib import Path

from .base import Store, check_rel
from .gdrive import GDRIVE_ROOT, open_gdrive
from .local import LocalStore
from .s3 import S3Store

__all__ = ["Store", "LocalStore", "S3Store", "open_store", "default_dest", "check_rel"]

_AWS_BUCKET_PREFIX = "s3://sloka-poc-audio-785703562757/pipeline"


def open_store(uri: str) -> Store:
    """s3://bucket/prefix -> S3Store; gdrive:[subdir] -> mounted Drive; else a local path."""
    uri = str(uri)
    if uri.startswith("s3://"):
        return S3Store.from_uri(uri)
    if uri.startswith("gdrive:"):
        return open_gdrive(uri[len("gdrive:"):])
    return LocalStore(Path(uri))


def default_dest(env: str, work: str) -> str:
    if env in ("aws", "kaggle"):
        return f"{_AWS_BUCKET_PREFIX}/{work}/"
    if env == "colab":
        return f"{GDRIVE_ROOT.as_posix()}/{work}/"
    repo = Path(__file__).resolve().parents[2]
    return f"{repo}/pipeline/output/{work}/"
