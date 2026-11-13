"""Append-only segment packs and their index lines.

A segment is `seg-<run_id>-<worker>-<seq:04d>` with files
  segments/<base>.audio.pack, .align.pack, .wav.pack (only if any wav), .idx.jsonl
The idx.jsonl is written and uploaded LAST: until it exists the segment is invisible.
Entries of compacted shards may carry explicit `audio_path`/`align_path`/`wav_path`
(store-relative) and `origin_segment` (the segment the blobs were copied from).
"""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .stores.base import Store

PACK_KINDS = ("audio", "align", "wav")
GOOD_STATUSES = ("ok", "align_failed")

ENTRY_DEFAULTS: dict[str, Any] = {
    "verse_id": None, "work": None, "book": None, "chapter": None, "seq": None,
    "status": "ok", "error": None, "text_variant": None, "text_fallback": 0,
    "duration_s": None, "syllables": None, "text_sha256": None, "params_hash": None,
    "steps": None, "seed": None, "voice": None, "meter": None, "mp3_kbps": None,
    "run_id": None,
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def seg_path(base: str, kind: str) -> str:
    return f"segments/{base}.{kind}.pack"


def idx_path(base: str) -> str:
    return f"segments/{base}.idx.jsonl"


def blob_path(entry: dict, kind: str) -> str:
    """Store-relative path of the pack holding this entry's blob of `kind`."""
    return entry.get(f"{kind}_path") or seg_path(entry["segment"], kind)


def origin(entry: dict) -> str:
    return entry.get("origin_segment") or entry.get("segment") or ""


def read_idx(text: str) -> list[dict]:
    """Parse idx.jsonl text; a trailing partial (or any malformed) line is ignored."""
    out: list[dict] = []
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


def _ident(e: dict) -> tuple:
    return (origin(e), e.get("created_at"))


def _rank(e: dict) -> tuple:
    return (e.get("created_at") or "", origin(e), e.get("segment") or "")


def winner(entries: list[dict]) -> dict:
    """D19: newest created_at wins (tie: greater segment name); failed never beats ok/align_failed."""
    if not entries:
        raise ValueError("winner() needs at least one entry")
    good = [e for e in entries if e.get("status") in GOOD_STATUSES]
    best = max(good or list(entries), key=_rank)
    out = dict(best)
    out["superseded_count"] = len({_ident(e) for e in entries} - {_ident(best)})
    return out


class SegmentWriter:
    def __init__(
        self,
        scratch_dir: Path,
        run_id: str,
        worker: str,
        store: Store | None,
        max_bytes: int = 256 * 1024 * 1024,
        max_age_s: float = 300,
    ):
        self.scratch = Path(scratch_dir)
        self.scratch.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id
        self.worker = worker
        self.store = store
        self.max_bytes = max_bytes
        self.max_age_s = max_age_s
        self._lock = threading.RLock()
        self._seq = 0
        self._base: str | None = None
        self._files: dict[str, Any] = {}
        self._sizes: dict[str, int] = {}
        self._entries: list[dict] = []
        self._opened_at = 0.0
        self._pending: list[tuple[str, list[str]]] = []  # sealed, not yet published

    # -- helpers
    def _local(self, base: str, kind: str) -> Path:
        return self.scratch / f"{base}.{kind}.pack"

    def _local_idx(self, base: str) -> Path:
        return self.scratch / f"{base}.idx.jsonl"

    def _open_segment(self) -> None:
        self._base = f"seg-{self.run_id}-{self.worker}-{self._seq:04d}"
        self._seq += 1
        self._files = {}
        self._sizes = {k: 0 for k in PACK_KINDS}
        self._entries = []
        self._opened_at = time.monotonic()

    def _append_blob(self, kind: str, blob: bytes) -> dict:
        assert self._base is not None
        f = self._files.get(kind)
        if f is None:
            f = open(self._local(self._base, kind), "ab")
            self._files[kind] = f
        off = self._sizes[kind]
        f.write(blob)
        self._sizes[kind] = off + len(blob)
        return {"off": off, "len": len(blob)}

    # -- public
    def add(self, entry: dict, mp3: bytes | None = None, align: bytes | None = None, wav: bytes | None = None) -> None:
        with self._lock:
            if self._base is None:
                self._open_segment()
            e = dict(ENTRY_DEFAULTS)
            e.update(entry)
            if e.get("extra") is None:
                e["extra"] = {}
            if not e.get("created_at"):
                e["created_at"] = now_iso()
            e["segment"] = self._base
            blobs = {"audio": mp3, "align": align, "wav": wav}
            if e["status"] == "failed":
                blobs = {k: None for k in blobs}
            for kind in PACK_KINDS:
                b = blobs[kind]
                e[kind] = self._append_blob(kind, b) if b else None
            self._entries.append(e)

    def _seal_locked(self) -> None:
        if self._base is None:
            return
        base = self._base
        if not self._entries:
            for f in self._files.values():
                f.close()
            for kind in list(self._files):
                p = self._local(base, kind)
                if p.exists():
                    p.unlink()
            self._reset()
            return
        kinds: list[str] = []
        for kind in PACK_KINDS:
            f = self._files.get(kind)
            if f is not None:
                f.flush()
                os.fsync(f.fileno())
                f.close()
                kinds.append(kind)
        # idx.jsonl last, fsynced
        tmp = self.scratch / f"{base}.idx.jsonl.writing"
        with open(tmp, "w", encoding="utf-8") as f:
            for e in self._entries:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self._local_idx(base))
        self._pending.append((base, kinds))
        self._reset()

    def _reset(self) -> None:
        self._base = None
        self._files = {}
        self._sizes = {}
        self._entries = []

    def _publish_pending_locked(self) -> list[str]:
        done: list[str] = []
        for base, kinds in list(self._pending):
            if self.store is not None:
                for kind in kinds:
                    self.store.put_file(self._local(base, kind), seg_path(base, kind))
                self.store.put_file(self._local_idx(base), idx_path(base))  # last
                for kind in kinds:
                    self._local(base, kind).unlink(missing_ok=True)
                self._local_idx(base).unlink(missing_ok=True)
            self._pending.remove((base, kinds))
            done.append(base)
        return done

    def maybe_seal(self) -> list[str]:
        with self._lock:
            if self._base is not None and self._entries:
                too_big = sum(self._sizes.values()) >= self.max_bytes
                too_old = (time.monotonic() - self._opened_at) >= self.max_age_s
                if too_big or too_old:
                    self._seal_locked()
            if self._pending:
                return self._publish_pending_locked()
            return []

    def seal(self) -> list[str]:
        """Seal the open segment and publish everything sealed. Returns base names
        (with no store they stay in scratch and are still returned)."""
        with self._lock:
            self._seal_locked()
            return self._publish_pending_locked()

    def close(self) -> list[str]:
        return self.seal()
