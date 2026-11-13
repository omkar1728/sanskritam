"""catalog.sqlite + manifest.json builders and the winner state of a store."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import shutil
from pathlib import Path
from typing import Any

from .segments import PACK_KINDS, _ident, blob_path, now_iso, read_idx, winner
from .stores.base import Store

SCHEMA_VERSION = 1
PIPELINE_VERSION = "0.1.0"
LEAD_MS = 400
NOTICES = [
    "Synthetic voice, not the original speaker.",
    "The voice belongs to Prof. Prathosh (IISc).",
]

_SCHEMA = """
CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE files(file_id INTEGER PRIMARY KEY, kind TEXT, path TEXT, bytes INTEGER, sha256 TEXT);
CREATE TABLE verses(
  verse_id TEXT PRIMARY KEY, work TEXT, book TEXT, chapter INTEGER, seq INTEGER,
  status TEXT, error TEXT,
  text_variant TEXT, text_fallback INTEGER,
  duration_s REAL,
  audio_file INTEGER, audio_off INTEGER, audio_len INTEGER,
  align_file INTEGER, align_off INTEGER, align_len INTEGER,
  wav_file INTEGER, wav_off INTEGER, wav_len INTEGER,
  syllables INTEGER, text_sha256 TEXT, params_hash TEXT,
  steps INTEGER, seed INTEGER, voice TEXT, meter TEXT, mp3_kbps INTEGER,
  run_id TEXT, created_at TEXT, superseded_count INTEGER, extra TEXT);
CREATE INDEX verses_order ON verses(work, book, chapter, seq);
CREATE INDEX verses_status ON verses(status);
"""


def read_all_entries(store: Store) -> list[dict]:
    """Every entry of every published idx.jsonl (segments and compacted shards)."""
    keys = [k for k in store.list("segments/") + store.list("shards/") if k.endswith(".idx.jsonl")]
    out: list[dict] = []
    for k in sorted(keys):
        try:
            text = store.read(k).decode("utf-8", errors="replace")
        except FileNotFoundError:
            continue
        for e in read_idx(text):
            if e.get("verse_id"):
                out.append(e)
    return out


def group_by_verse(entries: list[dict]) -> dict[str, list[dict]]:
    g: dict[str, list[dict]] = {}
    for e in entries:
        g.setdefault(e["verse_id"], []).append(e)
    return g


def load_state(store: Store) -> dict[str, dict]:
    """verse_id -> winning idx entry (D19)."""
    return {vid: winner(es) for vid, es in group_by_verse(read_all_entries(store)).items()}


def _blob_len(e: dict) -> int:
    return sum((e.get(k) or {}).get("len", 0) for k in PACK_KINDS)


def _prev_file_info(store: Store) -> dict[str, tuple[int, str]]:
    """Reuse sha256 values of immutable packs from an earlier manifest."""
    try:
        if not store.exists("manifest.json"):
            return {}
        m = json.loads(store.read("manifest.json"))
        return {f["path"]: (f["bytes"], f["sha256"]) for f in m.get("files", []) if f.get("sha256")}
    except Exception:  # noqa: BLE001
        return {}


def build_catalog(store: Store, db_path: Path) -> dict:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()

    groups = group_by_verse(read_all_entries(store))
    winners = {vid: winner(es) for vid, es in groups.items()}
    prev = _prev_file_info(store)

    superseded_bytes = 0
    for vid, es in groups.items():
        w_id = _ident(winners[vid])
        seen = {w_id}
        for e in es:
            i = _ident(e)
            if i in seen:
                continue
            seen.add(i)
            superseded_bytes += _blob_len(e)

    file_ids: dict[str, int] = {}
    files_info: list[dict] = []
    missing: list[str] = []

    def file_id(kind: str, path: str) -> int:
        if path in file_ids:
            return file_ids[path]
        fid = len(file_ids) + 1
        file_ids[path] = fid
        nbytes: int | None
        sha: str | None
        try:
            nbytes = store.size(path)
            cached = prev.get(path)
            sha = cached[1] if cached and cached[0] == nbytes else store.sha256(path)
        except Exception:  # noqa: BLE001
            nbytes, sha = None, None
            missing.append(path)
        files_info.append({"file_id": fid, "kind": kind, "path": path, "bytes": nbytes, "sha256": sha})
        return fid

    def sort_key(w: dict) -> tuple:
        return (w.get("work") or "", w.get("book") or "", w.get("chapter") or 0, w.get("seq") or 0, w["verse_id"])

    counts: dict[str, int] = {"ok": 0, "align_failed": 0, "failed": 0}
    kbps: set[int] = set()
    rows: list[dict] = []
    for w in sorted(winners.values(), key=sort_key):
        status = w.get("status") or "failed"
        counts[status] = counts.get(status, 0) + 1
        if w.get("mp3_kbps") is not None:
            kbps.add(int(w["mp3_kbps"]))
        row: dict[str, Any] = {
            "verse_id": w["verse_id"], "work": w.get("work"), "book": w.get("book"),
            "chapter": w.get("chapter"), "seq": w.get("seq"), "status": status, "error": w.get("error"),
            "text_variant": w.get("text_variant"), "text_fallback": int(bool(w.get("text_fallback"))),
            "duration_s": w.get("duration_s"), "syllables": w.get("syllables"),
            "text_sha256": w.get("text_sha256"), "params_hash": w.get("params_hash"),
            "steps": w.get("steps"), "seed": w.get("seed"), "voice": w.get("voice"),
            "meter": w.get("meter"), "mp3_kbps": w.get("mp3_kbps"), "run_id": w.get("run_id"),
            "created_at": w.get("created_at"), "superseded_count": w.get("superseded_count", 0),
            "extra": json.dumps(w.get("extra") or {}, ensure_ascii=False),
        }
        for kind in PACK_KINDS:
            b = w.get(kind) if status != "failed" else None
            if b:
                row[f"{kind}_file"] = file_id(kind, blob_path(w, kind))
                row[f"{kind}_off"] = b["off"]
                row[f"{kind}_len"] = b["len"]
            else:
                row[f"{kind}_file"] = row[f"{kind}_off"] = row[f"{kind}_len"] = None
        rows.append(row)

    con = sqlite3.connect(str(db_path))
    try:
        con.executescript(_SCHEMA)
        con.executemany(
            "INSERT INTO files(file_id, kind, path, bytes, sha256) VALUES(:file_id,:kind,:path,:bytes,:sha256)",
            files_info,
        )
        if rows:
            cols = list(rows[0].keys())
            con.executemany(
                f"INSERT INTO verses({','.join(cols)}) VALUES({','.join(':' + c for c in cols)})", rows
            )
        meta = {
            "schema_version": str(SCHEMA_VERSION),
            "pipeline_version": PIPELINE_VERSION,
            "mp3_kbps": ",".join(str(k) for k in sorted(kbps)),
            "lead_ms": str(LEAD_MS),
            "merged_at": now_iso(),
            "notices": json.dumps(NOTICES, ensure_ascii=False),
        }
        con.executemany("INSERT INTO meta(key, value) VALUES(?,?)", list(meta.items()))
        con.commit()
    finally:
        con.close()

    return {
        "counts": counts,
        "verses": len(rows),
        "superseded": sum(w.get("superseded_count", 0) for w in winners.values()),
        "superseded_bytes": superseded_bytes,
        "mp3_kbps": sorted(kbps),
        "files": [{k: f[k] for k in ("kind", "path", "bytes", "sha256")} for f in files_info],
        "missing_files": missing,
    }


def write_manifest(store: Store, counts: dict, files: list[dict], extra: dict | None = None) -> dict:
    manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "pipeline_version": PIPELINE_VERSION,
        "merged_at": now_iso(),
        "lead_ms": LEAD_MS,
        "notices": list(NOTICES),
        "counts": counts,
        "files": files,
    }
    if extra:
        manifest.update(extra)
    store.put_bytes("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"))
    return manifest


def _sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def publish_catalog(store: Store, work_dir: Path | None = None, extra: dict | None = None) -> dict:
    """Build catalog.sqlite locally, upload it, then write manifest.json. Returns build info + manifest."""
    own = work_dir is None
    work = Path(tempfile.mkdtemp(prefix="catalog-")) if own else Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)
    try:
        db = work / "catalog.sqlite"
        info = build_catalog(store, db)
        store.put_file(db, "catalog.sqlite")
        files = list(info["files"]) + [
            {"kind": "catalog", "path": "catalog.sqlite", "bytes": db.stat().st_size, "sha256": _sha256_file(db)}
        ]
        m_extra = {
            "verses": info["verses"],
            "superseded": info["superseded"],
            "superseded_bytes": info["superseded_bytes"],
            "mp3_kbps": info["mp3_kbps"],
        }
        if extra:
            m_extra.update(extra)
        manifest = write_manifest(store, info["counts"], files, m_extra)
        info["manifest"] = manifest
        return info
    finally:
        if own:
            shutil.rmtree(work, ignore_errors=True)
