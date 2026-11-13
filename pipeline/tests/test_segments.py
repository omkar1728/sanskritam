"""Segment writer/reader tests. All data are tiny FIXTURES, not real verses or audio."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.catalog import load_state
from pipeline.segments import SegmentWriter, idx_path, read_idx, seg_path, winner
from pipeline.stores.local import LocalStore

T0 = "2026-01-01T00:00:00.000000+00:00"
T1 = "2026-01-02T00:00:00.000000+00:00"
T2 = "2026-01-03T00:00:00.000000+00:00"


def mp3(tag: str) -> bytes:  # fixture: starts with an MPEG frame sync
    return b"\xff\xfb" + tag.encode() * 10


def align_json(tag: str) -> bytes:  # fixture alignment document
    return json.dumps({"audio_duration": 1.0, "lines": [{"tag": tag}]}).encode()


def mk_entry(vid: str, status: str = "ok", created_at: str = T0, book: str = "baala",
             chapter: int = 1, seq: int = 1, **kw) -> dict:
    e = {
        "verse_id": vid, "work": "ramayana", "book": book, "chapter": chapter, "seq": seq,
        "status": status, "error": "boom" if status == "failed" else None,
        "text_variant": "critical_smith", "text_fallback": 0, "duration_s": 9.2, "syllables": 32,
        "text_sha256": "t", "params_hash": "p", "steps": 10, "seed": 50, "voice": "v",
        "meter": "fixture", "mp3_kbps": 192, "run_id": "r", "created_at": created_at, "extra": {},
    }
    e.update(kw)
    return e


def write_segment(store, scratch: Path, run: str, items: list[tuple]) -> list[str]:
    """items: (entry, mp3, align, wav)."""
    w = SegmentWriter(scratch / f"scratch-{run}", run, "w0", store)
    for entry, a, b, c in items:
        w.add(entry, a, b, c)
    return w.seal()


class FlakyStore(LocalStore):
    fail_idx = True

    def put_file(self, local_path, rel):
        if self.fail_idx and rel.endswith(".idx.jsonl"):
            raise OSError("simulated upload failure")
        super().put_file(local_path, rel)


def test_writer_idx_read(tmp_path):
    store = LocalStore(tmp_path / "store")
    w = SegmentWriter(tmp_path / "scratch", "r1", "w0", store)
    w.add(mk_entry("v1"), mp3("a"), align_json("a"))
    w.add(mk_entry("v2", seq=2), mp3("bb"), align_json("bb"))
    w.add(mk_entry("v3", "failed", seq=3), mp3("zz"), None)  # failed carries no blobs
    bases = w.close()
    assert bases == ["seg-r1-w0-0000"]
    keys = store.list("segments/")
    assert idx_path(bases[0]) in keys and seg_path(bases[0], "audio") in keys
    assert seg_path(bases[0], "wav") not in keys
    entries = read_idx(store.read(idx_path(bases[0])).decode())
    assert [e["verse_id"] for e in entries] == ["v1", "v2", "v3"]
    e2 = entries[1]
    got = store.read_range(seg_path(bases[0], "audio"), e2["audio"]["off"], e2["audio"]["len"])
    assert got == mp3("bb")
    got = store.read_range(seg_path(bases[0], "align"), e2["align"]["off"], e2["align"]["len"])
    assert got == align_json("bb")
    assert entries[2]["audio"] is None and entries[2]["align"] is None
    assert all(e["segment"] == bases[0] for e in entries)
    assert not list((tmp_path / "scratch").glob("seg-*"))  # scratch deleted after upload


def test_wav_pack_only_when_present(tmp_path):
    store = LocalStore(tmp_path / "store")
    bases = write_segment(store, tmp_path, "r1", [(mk_entry("v1", "align_failed"), mp3("a"), None, b"RIFFxx")])
    assert seg_path(bases[0], "wav") in store.list("segments/")
    assert load_state(store)["v1"]["wav"]["len"] == 6


def test_empty_seal_writes_nothing(tmp_path):
    store = LocalStore(tmp_path / "store")
    w = SegmentWriter(tmp_path / "scratch", "r1", "w0", store)
    assert w.seal() == []
    assert store.list("") == []


def test_maybe_seal_by_size(tmp_path):
    store = LocalStore(tmp_path / "store")
    w = SegmentWriter(tmp_path / "scratch", "r1", "w0", store, max_bytes=10)
    w.add(mk_entry("v1"), mp3("a"), align_json("a"))
    assert w.maybe_seal() == ["seg-r1-w0-0000"]
    w.add(mk_entry("v2"), mp3("b"), align_json("b"))
    assert w.seal() == ["seg-r1-w0-0001"]


def test_crash_before_idx_is_invisible(tmp_path):
    store = FlakyStore(tmp_path / "store")
    w = SegmentWriter(tmp_path / "scratch", "r1", "w0", store)
    w.add(mk_entry("v1"), mp3("a"), align_json("a"))
    with pytest.raises(OSError):
        w.seal()
    keys = store.list("segments/")
    assert any(k.endswith(".audio.pack") for k in keys)
    assert not any(k.endswith(".idx.jsonl") for k in keys)
    assert load_state(store) == {}
    assert list((tmp_path / "scratch").glob("*.audio.pack"))  # scratch copy kept
    store.fail_idx = False
    assert w.seal() == ["seg-r1-w0-0000"]  # retried
    assert "v1" in load_state(store)


def test_unpublished_packs_without_idx(tmp_path):
    store = LocalStore(tmp_path / "store")
    store.put_bytes("segments/seg-x-w-0000.audio.pack", mp3("a"))
    assert load_state(store) == {}


def test_read_idx_ignores_partial_line():
    good = json.dumps({"verse_id": "v1"})
    text = good + "\n" + '{"verse_id": "v2", "sta'
    assert [e["verse_id"] for e in read_idx(text)] == ["v1"]
    assert read_idx("") == []


def _e(vid, status, created_at, segment):
    return {"verse_id": vid, "status": status, "created_at": created_at, "segment": segment}


def test_winner_newest_wins_and_counts():
    w = winner([_e("v", "ok", T0, "seg-a"), _e("v", "ok", T1, "seg-b")])
    assert w["segment"] == "seg-b" and w["superseded_count"] == 1


def test_winner_tie_greater_segment():
    w = winner([_e("v", "ok", T0, "seg-a"), _e("v", "ok", T0, "seg-b")])
    assert w["segment"] == "seg-b"


def test_winner_failed_never_beats_ok():
    w = winner([_e("v", "ok", T0, "seg-a"), _e("v", "failed", T2, "seg-b")])
    assert w["status"] == "ok" and w["superseded_count"] == 1
    w = winner([_e("v", "align_failed", T0, "seg-a"), _e("v", "failed", T2, "seg-b")])
    assert w["status"] == "align_failed"


def test_winner_failed_only():
    w = winner([_e("v", "failed", T0, "seg-a"), _e("v", "failed", T1, "seg-b")])
    assert w["status"] == "failed" and w["segment"] == "seg-b"


def test_winner_newer_ok_beats_older_failed():
    w = winner([_e("v", "failed", T0, "seg-a"), _e("v", "ok", T1, "seg-b")])
    assert w["status"] == "ok"
