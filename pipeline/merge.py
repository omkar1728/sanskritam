"""merge: copy missing segments from other stores into one, then rebuild catalog + manifest.

Only segments/ are copied (names are unique); shards/ names are not, so compacted
stores must be merged before compaction or used as the `into` store.
Only segments whose idx.jsonl exists in the source are copied (others are unpublished).
Idempotent: existing files are skipped.
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from .catalog import publish_catalog
from .stores import open_store
from .stores.base import Store


def _segment_groups(store: Store) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {}
    for key in store.list("segments/"):
        name = key[len("segments/"):]
        if "/" in name or ".tmp-" in name:
            continue
        groups.setdefault(name.split(".", 1)[0], []).append(key)
    return groups


def merge(into_uri: str, from_uris: list[str], work_dir: Path | None = None) -> dict:
    into = open_store(into_uri)
    own = work_dir is None
    work = Path(tempfile.mkdtemp(prefix="merge-")) if own else Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    skipped = 0
    try:
        tmp = work / "copy.bin"
        for uri in from_uris:
            src = open_store(uri)
            if src.root == into.root:
                continue
            for base, keys in sorted(_segment_groups(src).items()):
                idx_key = f"segments/{base}.idx.jsonl"
                if idx_key not in keys:
                    continue  # unpublished segment
                ordered = [k for k in sorted(keys) if k != idx_key] + [idx_key]
                did = False
                for key in ordered:
                    if into.exists(key):
                        continue
                    src.get_file(key, tmp)
                    into.put_file(tmp, key)
                    tmp.unlink(missing_ok=True)
                    did = True
                if did:
                    copied.append(base)
                else:
                    skipped += 1
        info = publish_catalog(
            into,
            work,
            extra={"last_merge": {"sources": list(from_uris), "copied_segments": len(copied)}},
        )
        return {
            "into": into.root,
            "copied": copied,
            "skipped": skipped,
            "counts": info["counts"],
            "verses": info["verses"],
            "superseded": info["superseded"],
            "superseded_bytes": info["superseded_bytes"],
            "missing_files": info["missing_files"],
            "manifest": info["manifest"],
        }
    finally:
        if own:
            shutil.rmtree(work, ignore_errors=True)
