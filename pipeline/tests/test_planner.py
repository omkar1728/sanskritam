"""FIXTURE tests: placeholder padas only."""
import pytest

from pipeline.planner import (Selection, parse_chapters, parse_shard, select, shard_of, summarize)
from pipeline.schema import effective_params, load_defaults, params_hash, parse_record

D = load_defaults()


def mk(vid, book="baala", ch=1, seq=1):
    return parse_record({"verse_id": vid, "book": book, "chapter": ch, "seq": seq, "work": "ramayana",
                         "padas": [f"FIXTURE {vid} pada one"]})


RECS = [mk(f"{b}-{c:03d}-{s:03d}", b, c, s) for b in ("baala", "ayodhya") for c in (1, 2, 3) for s in (1, 2, 3)]


def ids(jobs):
    return [j.record.verse_id for j in jobs]


def test_parse_chapters():
    assert parse_chapters("1-5,8") == {1, 2, 3, 4, 5, 8}
    assert parse_shard("2/4") == (2, 4)
    with pytest.raises(ValueError):
        parse_shard("4/4")


@pytest.mark.parametrize("k", range(1, 9))
def test_shard_exactly_once(k):
    seen = []
    for i in range(k):
        seen += ids(select(RECS, {}, Selection(shard=(i, k)), D))
    assert sorted(seen) == sorted(r.verse_id for r in RECS)
    assert shard_of("baala-001-001", k) == shard_of("baala-001-001", k)


def test_shard_with_filter_exactly_once():
    seen = []
    for i in range(3):
        seen += ids(select(RECS, {}, Selection(book=["ayodhya"], chapters={1, 2}, shard=(i, 3)), D))
    assert sorted(seen) == sorted(r.verse_id for r in RECS if r.book == "ayodhya" and r.chapter in (1, 2))


def test_filters():
    assert len(select(RECS, {}, Selection(book=["baala"]), D)) == 9
    assert len(select(RECS, {}, Selection(chapters={2}), D)) == 6
    assert ids(select(RECS, {}, Selection(ids={"baala-001-002"}), D)) == ["baala-001-002"]
    assert len(select(RECS, {}, Selection(limit=4), D)) == 4


def test_order():
    out = select(list(reversed(RECS)), {}, Selection(), D)
    # book order of appearance (ayodhya first in reversed input), then chapter, seq
    assert out[0].record.book == "ayodhya" and ids(out[:3]) == ["ayodhya-001-001", "ayodhya-001-002", "ayodhya-001-003"]


def _entry(rec, status, **kw):
    p = effective_params(rec, D, {})
    e = {"status": status, "text_sha256": rec.text_sha256(), "params_hash": params_hash(p)}
    e.update(kw)
    return e


def test_skip_done_and_force():
    a, b, c = RECS[0], RECS[1], RECS[2]
    state = {a.verse_id: _entry(a, "ok"),
             b.verse_id: {**_entry(b, "ok"), "text_sha256": "stale"},
             c.verse_id: {**_entry(c, "ok"), "params_hash": "stale"}}
    got = ids(select(RECS[:3], state, Selection(), D))
    assert a.verse_id not in got and b.verse_id in got and c.verse_id in got
    assert len(select(RECS[:3], state, Selection(force=True), D)) == 3
    # cli param change invalidates
    assert a.verse_id in ids(select(RECS[:3], state, Selection(), D, {"steps": 16}))


def test_only_semantics():
    a, b, c, d = RECS[:4]
    state = {a.verse_id: _entry(a, "ok"), b.verse_id: _entry(b, "failed"),
             c.verse_id: _entry(c, "align_failed")}
    recs = RECS[:4]
    assert ids(select(recs, state, Selection(only="missing"), D)) == [d.verse_id]
    assert ids(select(recs, state, Selection(only="failed"), D)) == [b.verse_id]
    af = select(recs, state, Selection(only="align_failed"), D)
    assert ids(af) == [c.verse_id] and af[0].reuse == "wav"
    assert all(j.reuse is None for j in select(recs, state, Selection(), D))
    with pytest.raises(ValueError):
        select(recs, state, Selection(only="bogus"), D)


def test_summarize():
    jobs = select(RECS, {}, Selection(limit=5), D)
    s = summarize(jobs, len(RECS), 2)
    assert s["selected"] == 5 and s["total_in"] == 18 and s["skipped_done"] == 2 and s["by_book"] == {"baala": 5}
