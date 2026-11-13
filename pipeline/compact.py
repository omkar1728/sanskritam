"""compact: copy only winning blobs into shards, rebuild catalog + manifest.

Shard unit n of a book: shards/audio-<book>-<n>.pack, align-<book>-<n>.pack,
(wav-<book>-<n>.pack for align_failed winners) and shards/shard-<book>-<n>.idx.jsonl (written last).
Shard idx entries keep created_at/status and carry explicit *_path keys plus
origin_segment, so load_state() gives the same winners after compaction.
"""
from __future__ import annotations

import json
import re
import shutil
import tempfile
from pathlib import Path

from .catalog import group_by_verse, publish_catalog, read_all_entries
from .segments import blob_path, origin, winner
from .stores import open_store
from .stores.base import Store
from .verify import verify

SHARD_BYTES = 256 * 1024 * 1024
_IDX_RE = re.compile(r"^shards/shard-(?P<book>.+)-(?P<n>\d{4})\.idx\.jsonl$")
_DROP = ("superseded_count", "audio_path", "align_path", "wav_path")


def _safe_book(book: str | None) -> str:
    return re.sub(r"[^A-Za-z0-9_]+", "_", book or "unknown") or "unknown"


class _Unit:
    def __init__(self, store: Store, work: Path, book: str, n: int):
        self.store, self.work, self.book, self.n = store, work, book, n
        self.base = f"shard-{book}-{n:04d}"
        self.files: dict[str, object] = {}
        self.sizes = {"audio": 0, "align": 0, "wav": 0}
        self.entries: list[dict] = []

    def rel(self, kind: str) -> str:
        return f"shards/{kind}-{self.book}-{self.n:04d}.pack"

    def local(self, kind: str) -> Path:
        return self.work / f"{kind}-{self.book}-{self.n:04d}.pack"

    def append(self, kind: str, data: bytes) -> dict:
        f = self.files.get(kind)
        if f is None:
            f = open(self.local(kind), "ab")
            self.files[kind] = f
        off = self.sizes[kind]
        f.write(data)  # type: ignore[attr-defined]
        self.sizes[kind] = off + len(data)
        return {"off": off, "len": len(data)}

    def flush(self) -> list[str]:
        written: list[str] = []
        if not self.entries:
            return written
        for f in self.files.values():
            f.close()  # type: ignore[attr-defined]
        for kind in self.files:
            self.store.put_file(self.local(kind), self.rel(kind))
            written.append(self.rel(kind))
            self.local(kind).unlink(missing_ok=True)
        idx = "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in self.entries)
        key = f"shards/{self.base}.idx.jsonl"
        self.store.put_bytes(key, idx.encode("utf-8"))  # last
        written.append(key)
        return written


def compact(store_uri: str, delete_old: bool = False, work_dir: Path | None = None,
            shard_bytes: int = SHARD_BYTES) -> dict:
    store = open_store(store_uri)
    own = work_dir is None
    work = Path(tempfile.mkdtemp(prefix="compact-")) if own else Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)
    try:
        groups = group_by_verse(read_all_entries(store))
        winners = [winner(es) for es in groups.values()]

        next_n: dict[str, int] = {}
        for key in store.list("shards/"):
            m = _IDX_RE.match(key)
            if m:
                b = m.group("book")
                next_n[b] = max(next_n.get(b, 0), int(m.group("n")) + 1)

        by_book: dict[str, list[dict]] = {}
        for w in winners:
            by_book.setdefault(_safe_book(w.get("book")), []).append(w)

        written: list[str] = []
        for book, ws in sorted(by_book.items()):
            ws.sort(key=lambda w: (w.get("chapter") or 0, w.get("seq") or 0, w["verse_id"]))
            unit: _Unit | None = None
            for w in ws:
                if unit is None:
                    n = next_n.get(book, 0)
                    next_n[book] = n + 1
                    unit = _Unit(store, work, book, n)
                status = w.get("status")
                ne = {k: v for k, v in w.items() if k not in _DROP}
                ne["origin_segment"] = origin(w)
                ne["segment"] = unit.base
                keep = ("audio", "align") + (("wav",) if status == "align_failed" else ())
                for kind in ("audio", "align", "wav"):
                    b = w.get(kind) if status != "failed" and kind in keep else None
                    if b:
                        data = store.read_range(blob_path(w, kind), b["off"], b["len"])
                        if len(data) != b["len"]:
                            raise RuntimeError(f"short read for {w['verse_id']} {kind}: {len(data)} != {b['len']}")
                        ne[kind] = unit.append(kind, data)
                        ne[f"{kind}_path"] = unit.rel(kind)
                    else:
                        ne[kind] = None
                        ne[f"{kind}_path"] = None
                unit.entries.append(ne)
                if unit.sizes["audio"] >= shard_bytes or unit.sizes["align"] >= shard_bytes:
                    written += unit.flush()
                    unit = None
            if unit is not None:
                written += unit.flush()

        info = publish_catalog(store, work)
        result = verify(store_uri)
        deleted: list[str] = []
        if delete_old and result["ok"]:
            keep_keys = set(written)
            for key in store.list("segments/"):
                store.delete(key)
                deleted.append(key)
            for key in store.list("shards/"):
                if key not in keep_keys:
                    store.delete(key)
                    deleted.append(key)
            info = publish_catalog(store, work)
            result = verify(store_uri)
        return {
            "winners": len(winners),
            "shard_files": written,
            "deleted": deleted,
            "counts": info["counts"],
            "superseded": info["superseded"],
            "superseded_bytes": info["superseded_bytes"],
            "verify": result,
        }
    finally:
        if own:
            shutil.rmtree(work, ignore_errors=True)
