"""Google Drive store: Drive is only reachable through the Colab mount, so it is a LocalStore."""
from __future__ import annotations

from pathlib import Path

from .base import check_rel
from .local import LocalStore

GDRIVE_ROOT = Path("/content/drive/MyDrive/sloka_pipeline")


def open_gdrive(subdir: str = "") -> LocalStore:
    subdir = subdir.strip("/")
    if subdir:
        check_rel(subdir)
    return LocalStore(GDRIVE_ROOT / subdir if subdir else GDRIVE_ROOT)
