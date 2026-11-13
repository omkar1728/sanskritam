"""Local directory store (also used for the mounted Google Drive)."""
from __future__ import annotations

import hashlib
import os
import shutil
import uuid
from pathlib import Path

from .base import Store, check_rel

TMP_MARK = ".tmp-"


class LocalStore(Store):
    def __init__(self, root: Path | str):
        self._root = Path(root)

    @property
    def root(self) -> str:
        return str(self._root)

    def _path(self, rel: str) -> Path:
        check_rel(rel)
        return self._root.joinpath(*rel.split("/"))

    def list(self, prefix: str) -> list[str]:
        check_rel(prefix, allow_empty=True)
        if not self._root.is_dir():
            return []
        out: list[str] = []
        # Narrow the walk to the deepest complete directory of the prefix.
        start = self._root
        if "/" in prefix:
            sub = prefix.rsplit("/", 1)[0]
            start = self._root.joinpath(*sub.split("/"))
            if not start.is_dir():
                return []
        for dirpath, _dirs, files in os.walk(start):
            for name in files:
                if TMP_MARK in name:
                    continue
                full = Path(dirpath) / name
                rel = full.relative_to(self._root).as_posix()
                if rel.startswith(prefix):
                    out.append(rel)
        return sorted(out)

    def exists(self, rel: str) -> bool:
        return self._path(rel).is_file()

    def read(self, rel: str) -> bytes:
        return self._path(rel).read_bytes()

    def read_range(self, rel: str, off: int, length: int) -> bytes:
        if off < 0 or length < 0:
            raise ValueError("negative range")
        with open(self._path(rel), "rb") as f:
            f.seek(off)
            return f.read(length)

    def size(self, rel: str) -> int:
        return self._path(rel).stat().st_size

    def sha256(self, rel: str, chunk: int = 8 * 1024 * 1024) -> str:
        h = hashlib.sha256()
        with open(self._path(rel), "rb") as f:
            while True:
                b = f.read(chunk)
                if not b:
                    break
                h.update(b)
        return h.hexdigest()

    @staticmethod
    def _tmp_for(dest: Path) -> Path:
        return dest.with_name(dest.name + TMP_MARK + uuid.uuid4().hex[:8])

    def put_file(self, local_path: Path, rel: str) -> None:
        dest = self._path(rel)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._tmp_for(dest)
        try:
            with open(local_path, "rb") as src, open(tmp, "wb") as dst:
                shutil.copyfileobj(src, dst, 1024 * 1024)
                dst.flush()
                os.fsync(dst.fileno())
            os.replace(tmp, dest)
        finally:
            if tmp.exists():
                tmp.unlink()

    def put_bytes(self, rel: str, data: bytes) -> None:
        dest = self._path(rel)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._tmp_for(dest)
        try:
            with open(tmp, "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, dest)
        finally:
            if tmp.exists():
                tmp.unlink()

    def get_file(self, rel: str, local_path: Path) -> None:
        src = self._path(rel)
        local_path = Path(local_path)
        local_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._tmp_for(local_path)
        try:
            shutil.copyfile(src, tmp)
            os.replace(tmp, local_path)
        finally:
            if tmp.exists():
                tmp.unlink()

    def delete(self, rel: str) -> None:
        p = self._path(rel)
        try:
            p.unlink()
        except FileNotFoundError:
            pass
