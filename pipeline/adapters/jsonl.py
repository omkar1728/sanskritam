"""JSONL adapter: .jsonl or .jsonl.zst, paths or globs."""
from __future__ import annotations

import glob
import io
import json
from pathlib import Path

from ..schema import parse_record


def expand(paths) -> list:
    out = []
    for p in ([paths] if isinstance(paths, (str, Path)) else paths):
        p = str(p)
        hits = sorted(glob.glob(p))
        if not hits:
            hits = [p]  # let open() report the missing file
        out.extend(hits)
    return out


def _open(path: str):
    if path.endswith(".zst"):
        try:
            import zstandard
        except ImportError as e:
            raise RuntimeError(f"{path}: reading .zst needs the 'zstandard' package (pip install zstandard)") from e
        fh = open(path, "rb")
        return io.TextIOWrapper(zstandard.ZstdDecompressor().stream_reader(fh), encoding="utf-8")
    return open(path, "r", encoding="utf-8")


def iter_records(paths, on_invalid=None):
    for path in expand(paths):
        with _open(path) as fh:
            for n, line in enumerate(fh, 1):
                line = line.strip()
                if not line:
                    continue
                where = f"line {n}"
                try:
                    d = json.loads(line)
                    where = f"line {n} ({d.get('verse_id')})" if isinstance(d, dict) else where
                    yield parse_record(d)
                except ValueError as e:  # includes JSONDecodeError
                    if on_invalid:
                        on_invalid(path, where, str(e))
