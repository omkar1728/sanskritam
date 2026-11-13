"""merge / compact / verify / catalog tests. Fixture blobs only."""
from __future__ import annotations

import json
import sqlite3

from pipeline.catalog import build_catalog, load_state
from pipeline.compact import compact
from pipeline.merge import merge
from pipeline.segments import blob_path
from pipeline.stores.local import LocalStore
from pipeline.tests.test_segments import T0, T1, T2, align_json, mk_entry, mp3, write_segment
from pipeline.verify import verify


def _item(vid, tag, status="ok", created_at=T0, **kw):
    if status == "failed":
        return (mk_entry(vid, status, created_at, **kw), None, None, None)
    if status == "align_failed":
        return (mk_entry(vid, status, created_at, **kw), mp3(tag), None, b"RIFF" + tag.encode())
    return (mk_entry(vid, status, created_at, **kw), mp3(tag), align_json(tag), None)


def _blobs(store, entry):
    out = {}
    for kind in ("audio", "align", "wav"):
        b = entry.get(kind)
        out[kind] = store.read_range(blob_path(entry, kind), b["off"], b["len"]) if b else None
    return out


def _summary(store):
    st = load_state(store)
    return {
        vid: (e["status"], e["created_at"], _blobs(store, e))
        for vid, e in st.items()
    }


def _two_stores(tmp_path):
    a = LocalStore(tmp_path / "A")
    b = LocalStore(tmp_path / "B")
    write_segment(a, tmp_path, "ra", [_item("v1", "a1", seq=1), _item("v2", "a2", seq=2, chapter=1)])
    write_segment(b, tmp_path, "rb", [
        _item("v1", "b1", created_at=T1, seq=1),            # newer than A's v1
        _item("v3", "b3", "align_failed", seq=3),
        _item("v2", "bad", "failed", created_at=T2, seq=2),  # newer failed must not hide A's ok v2
        _item("v4", "b4", "failed", seq=4, book="ayodhya"),
    ])
    return a, b


def test_merge_newest_wins_and_failed_never_beats_ok(tmp_path):
    a, b = _two_stores(tmp_path)
    res = merge(str(tmp_path / "A"), [str(tmp_path / "B")], work_dir=tmp_path / "w")
    assert len(res["copied"]) == 1
    st = load_state(a)
    assert st["v1"]["run_id"] == "r" and _blobs(a, st["v1"])["audio"] == mp3("b1")
    assert st["v1"]["superseded_count"] == 1
    assert st["v2"]["status"] == "ok" and _blobs(a, st["v2"])["audio"] == mp3("a2")
    assert st["v3"]["status"] == "align_failed" and _blobs(a, st["v3"])["wav"] == b"RIFFb3"
    assert st["v4"]["status"] == "failed"
    assert res["counts"] == {"ok": 2, "align_failed": 1, "failed": 1}
    assert res["superseded"] == 2
    assert res["superseded_bytes"] > 0
    assert a.exists("catalog.sqlite") and a.exists("manifest.json")
    man = json.loads(a.read("manifest.json"))
    assert man["notices"][0] == "Synthetic voice, not the original speaker."
    assert any(f["path"] == "catalog.sqlite" and f["sha256"] for f in man["files"])
    assert verify(str(tmp_path / "A"))["ok"]


def test_catalog_schema(tmp_path):
    a, b = _two_stores(tmp_path)
    merge(str(tmp_path / "A"), [str(tmp_path / "B")], work_dir=tmp_path / "w")
    db = tmp_path / "cat.sqlite"
    a.get_file("catalog.sqlite", db)
    con = sqlite3.connect(db)
    meta = dict(con.execute("SELECT key, value FROM meta"))
    assert meta["schema_version"] == "1" and meta["lead_ms"] == "400" and meta["mp3_kbps"] == "192"
    assert "merged_at" in meta and "notices" in meta
    (n,) = con.execute("SELECT count(*) FROM verses").fetchone()
    assert n == 4
    row = con.execute("SELECT status, audio_len, align_file, wav_len FROM verses WHERE verse_id='v3'").fetchone()
    assert row[0] == "align_failed" and row[1] > 0 and row[2] is None and row[3] > 0
    idx = {r[1] for r in con.execute("PRAGMA index_list(verses)")}
    assert {"verses_order", "verses_status"} <= idx
    con.close()


def test_merge_idempotent_with_overlap(tmp_path):
    a, b = _two_stores(tmp_path)
    r1 = merge(str(tmp_path / "A"), [str(tmp_path / "B")], work_dir=tmp_path / "w")
    keys1 = a.list("segments/")
    s1 = _summary(a)
    r2 = merge(str(tmp_path / "A"), [str(tmp_path / "B")], work_dir=tmp_path / "w")
    assert r2["copied"] == [] and r2["skipped"] >= 1
    assert a.list("segments/") == keys1
    assert _summary(a) == s1
    assert r1["counts"] == r2["counts"]
    # merging A into itself or B into A again from an overlapping store is harmless
    r3 = merge(str(tmp_path / "A"), [str(tmp_path / "A"), str(tmp_path / "B")], work_dir=tmp_path / "w")
    assert r3["copied"] == []


def test_merge_skips_unpublished_segment(tmp_path):
    a = LocalStore(tmp_path / "A")
    b = LocalStore(tmp_path / "B")
    b.put_bytes("segments/seg-x-w-0000.audio.pack", mp3("a"))  # no idx: crashed writer
    res = merge(str(tmp_path / "A"), [str(tmp_path / "B")], work_dir=tmp_path / "w")
    assert res["copied"] == [] and a.list("segments/") == []


def test_compact_keeps_load_state(tmp_path):
    a, b = _two_stores(tmp_path)
    merge(str(tmp_path / "A"), [str(tmp_path / "B")], work_dir=tmp_path / "w")
    before = _summary(a)
    res = compact(str(tmp_path / "A"), delete_old=False, work_dir=tmp_path / "wc", shard_bytes=40)
    assert res["verify"]["ok"], res["verify"]["errors"]
    assert any(k.startswith("shards/audio-baala-") for k in res["shard_files"])
    assert _summary(a) == before  # winners unchanged even with old segments still present
    # wav kept only for the align_failed winner
    st = load_state(a)
    assert st["v3"]["wav"] is not None and st["v1"].get("wav") is None
    # now delete old
    res = compact(str(tmp_path / "A"), delete_old=True, work_dir=tmp_path / "wc", shard_bytes=40)
    assert res["verify"]["ok"], res["verify"]["errors"]
    assert a.list("segments/") == []
    assert _summary(a) == before
    assert verify(str(tmp_path / "A"))["ok"]
    cat = build_catalog(a, tmp_path / "again.sqlite")
    assert cat["counts"] == {"ok": 2, "align_failed": 1, "failed": 1}


def test_compact_does_not_delete_when_verify_fails(tmp_path):
    a = LocalStore(tmp_path / "A")
    write_segment(a, tmp_path, "ra", [_item("v1", "a1")])
    # corrupt: a winner whose align JSON is not parseable
    write_segment(a, tmp_path, "rb", [(mk_entry("v2", created_at=T1), mp3("x"), b"not json", None)])
    res = compact(str(tmp_path / "A"), delete_old=True, work_dir=tmp_path / "wc")
    assert not res["verify"]["ok"]
    assert a.list("segments/")  # old segments retained


def test_verify_detects_truncated_pack(tmp_path):
    a = LocalStore(tmp_path / "A")
    write_segment(a, tmp_path, "ra", [_item("v1", "a1", seq=1), _item("v2", "a2", seq=2)])
    merge(str(tmp_path / "A"), [], work_dir=tmp_path / "w")
    assert verify(str(tmp_path / "A"))["ok"]
    pack = next(k for k in a.list("segments/") if k.endswith(".audio.pack"))
    p = tmp_path / "A" / pack
    data = p.read_bytes()
    p.write_bytes(data[: len(data) // 2])
    res = verify(str(tmp_path / "A"))
    assert not res["ok"]
    assert any("size" in e or "beyond" in e or "sha256" in e for e in res["errors"])
    assert res["checked"] == 2


def test_verify_detects_bad_mp3_and_bad_align(tmp_path):
    a = LocalStore(tmp_path / "A")
    write_segment(a, tmp_path, "ra", [
        (mk_entry("v1"), b"\x00\x00notmp3", align_json("a"), None),
        (mk_entry("v2", seq=2), mp3("b"), b'{"nolines": 1}', None),
    ])
    merge(str(tmp_path / "A"), [], work_dir=tmp_path / "w")
    res = verify(str(tmp_path / "A"))
    assert not res["ok"]
    assert any("v1" in e and "MP3" in e for e in res["errors"])
    assert any("v2" in e and "lines" in e for e in res["errors"])


def test_verify_without_catalog(tmp_path):
    assert verify(str(tmp_path / "empty"))["ok"] is False
