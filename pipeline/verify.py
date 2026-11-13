"""verify: check catalog rows against the files in the store."""
from __future__ import annotations

import json
import random
import shutil
import sqlite3
import tempfile
from pathlib import Path

from .stores import open_store


def _mp3_ok(head: bytes) -> bool:
    if head[:3] == b"ID3":
        return True
    return len(head) >= 2 and head[0] == 0xFF and (head[1] & 0xE0) == 0xE0


def verify(store_uri: str, sample: float = 1.0) -> dict:
    store = open_store(store_uri)
    errors: list[str] = []
    checked = 0
    if not store.exists("catalog.sqlite"):
        return {"ok": False, "errors": ["catalog.sqlite missing"], "checked": 0}
    tmp = Path(tempfile.mkdtemp(prefix="verify-"))
    rng = random.Random(0)
    try:
        db = tmp / "catalog.sqlite"
        store.get_file("catalog.sqlite", db)
        con = sqlite3.connect(str(db))
        con.row_factory = sqlite3.Row
        try:
            files = {r["file_id"]: dict(r) for r in con.execute("SELECT * FROM files")}
            rows = [dict(r) for r in con.execute("SELECT * FROM verses ORDER BY verse_id")]
        finally:
            con.close()

        manifest = None
        if store.exists("manifest.json"):
            try:
                manifest = json.loads(store.read("manifest.json"))
            except ValueError:
                errors.append("manifest.json is not valid JSON")
        else:
            errors.append("manifest.json missing")
        mfiles = {f["path"]: f for f in (manifest or {}).get("files", [])}

        sizes: dict[int, int | None] = {}
        for fid, f in files.items():
            path = f["path"]
            try:
                size = store.size(path)
            except Exception as e:  # noqa: BLE001
                errors.append(f"{path}: missing ({type(e).__name__})")
                sizes[fid] = None
                continue
            sizes[fid] = size
            if f["bytes"] is not None and f["bytes"] != size:
                errors.append(f"{path}: size {size} != catalog {f['bytes']}")
            if f["sha256"] and (sample >= 1.0 or rng.random() < sample):
                actual = store.sha256(path)
                if actual != f["sha256"]:
                    errors.append(f"{path}: sha256 mismatch")
            mf = mfiles.get(path)
            if mf:
                if mf.get("sha256") and f["sha256"] and mf["sha256"] != f["sha256"]:
                    errors.append(f"{path}: manifest sha256 differs from catalog")
                if mf.get("bytes") is not None and f["bytes"] is not None and mf["bytes"] != f["bytes"]:
                    errors.append(f"{path}: manifest bytes differ from catalog")
        cat = mfiles.get("catalog.sqlite")
        if cat and cat.get("sha256") and sample >= 1.0:
            # the uploaded catalog must match what the manifest recorded
            import hashlib

            if hashlib.sha256(db.read_bytes()).hexdigest() != cat["sha256"]:
                errors.append("catalog.sqlite: sha256 differs from manifest")

        for r in rows:
            if sample < 1.0 and rng.random() >= sample:
                continue
            checked += 1
            vid = r["verse_id"]
            status = r["status"]
            if status not in ("ok", "align_failed", "failed"):
                errors.append(f"{vid}: bad status {status!r}")
                continue
            if status == "failed":
                if not r["error"]:
                    errors.append(f"{vid}: failed without error")
                if r["audio_file"] is not None:
                    errors.append(f"{vid}: failed but has audio")
                continue
            expected = {"audio": True, "align": status == "ok", "wav": status == "align_failed"}
            for kind, required in expected.items():
                fid, off, ln = r[f"{kind}_file"], r[f"{kind}_off"], r[f"{kind}_len"]
                if fid is None:
                    if required:
                        errors.append(f"{vid}: {status} but no {kind} blob")
                    continue
                f = files.get(fid)
                if f is None:
                    errors.append(f"{vid}: {kind} file_id {fid} not in files")
                    continue
                size = sizes.get(fid)
                if off is None or ln is None or off < 0 or ln <= 0:
                    errors.append(f"{vid}: bad {kind} offset/length")
                    continue
                if size is None or off + ln > size:
                    errors.append(f"{vid}: {kind} range {off}+{ln} beyond {f['path']} (size {size})")
                    continue
                if kind == "audio":
                    head = store.read_range(f["path"], off, min(ln, 4))
                    if not _mp3_ok(head):
                        errors.append(f"{vid}: audio has no MP3 frame sync/ID3 header")
                elif kind == "align":
                    data = store.read_range(f["path"], off, ln)
                    try:
                        doc = json.loads(data.decode("utf-8"))
                    except ValueError:
                        errors.append(f"{vid}: alignment JSON does not parse")
                        continue
                    if not isinstance(doc, dict) or "lines" not in doc:
                        errors.append(f"{vid}: alignment JSON has no 'lines'")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return {"ok": not errors, "errors": errors, "checked": checked}
