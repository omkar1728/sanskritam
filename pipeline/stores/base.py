"""Store interface: a flat key/value view over a directory or an S3 prefix.

All relative keys use '/' and never contain '..'.
"""
from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from pathlib import Path


def check_rel(rel: str, allow_empty: bool = False) -> str:
    """Reject keys that could escape the store root."""
    if not isinstance(rel, str):
        raise TypeError(f"store key must be str, got {type(rel).__name__}")
    if rel == "":
        if allow_empty:
            return rel
        raise ValueError("empty store key")
    if "\\" in rel or "\x00" in rel or rel.startswith("/"):
        raise ValueError(f"invalid store key: {rel!r}")
    if any(part == ".." for part in rel.split("/")):
        raise ValueError(f"'..' not allowed in store key: {rel!r}")
    return rel


class Store(ABC):
    @property
    @abstractmethod
    def root(self) -> str:
        """Display string of the store root."""

    @abstractmethod
    def list(self, prefix: str) -> list[str]:
        """Relative keys that start with prefix, sorted."""

    @abstractmethod
    def exists(self, rel: str) -> bool: ...

    @abstractmethod
    def read(self, rel: str) -> bytes: ...

    @abstractmethod
    def read_range(self, rel: str, off: int, length: int) -> bytes: ...

    @abstractmethod
    def put_file(self, local_path: Path, rel: str) -> None:
        """Copy a local file into the store. Never deletes the local file."""

    @abstractmethod
    def put_bytes(self, rel: str, data: bytes) -> None: ...

    @abstractmethod
    def get_file(self, rel: str, local_path: Path) -> None: ...

    @abstractmethod
    def delete(self, rel: str) -> None: ...

    # Non-abstract helpers (subclasses should override for efficiency).
    def size(self, rel: str) -> int:
        return len(self.read(rel))

    def sha256(self, rel: str, chunk: int = 8 * 1024 * 1024) -> str:
        total = self.size(rel)
        h = hashlib.sha256()
        off = 0
        while off < total:
            data = self.read_range(rel, off, min(chunk, total - off))
            if not data:
                break
            h.update(data)
            off += len(data)
        return h.hexdigest()

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.root!r})"
