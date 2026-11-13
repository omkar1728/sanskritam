"""FIXTURE tests. Real text only for baala-001-001; other padas are placeholders."""
import pytest

from pipeline.schema import (ENGINE_VERSION, JobRecord, effective_params, load_defaults, params_hash,
                             parse_record)

REAL = ["तपःस्वाध्यायनिरतं तपस्वी वाग्विदां वरम्", "नारदं परिपप्रच्छ वाल्मीकिर्मुनिपुंगवम्"]  # baala-001-001 critical_smith


def test_parse_ok_and_extra():
    r = parse_record({"verse_id": "baala-001-001", "padas": REAL, "foo": 1, "chapter": "1"})
    assert r.padas == REAL and r.extra == {"foo": 1} and r.chapter == 1 and r.schema == 1
    assert r.to_dict()["foo"] == 1


def test_danda_stripped():
    r = parse_record({"verse_id": "x-1", "padas": ["FIXTURE pada one ।", " FIXTURE pada two ॥ "]})
    assert r.padas == ["FIXTURE pada one", "FIXTURE pada two"]


@pytest.mark.parametrize("d", [
    {"verse_id": "Bad Id", "padas": ["a"]},
    {"verse_id": "", "padas": ["a"]},
    {"verse_id": "x", "padas": []},
    {"verse_id": "x", "padas": ["a", " ।"]},
    {"verse_id": "x", "padas": "abc"},
    {"verse_id": "x", "padas": ["a"], "schema": 2},
    {"padas": ["a"]},
])
def test_parse_bad(d):
    with pytest.raises(ValueError):
        parse_record(d)


def test_text_sha256_stable():
    a = JobRecord(verse_id="a", padas=["p", "q"])
    b = JobRecord(verse_id="b", padas=["p", "q"])
    assert a.text_sha256() == b.text_sha256()
    assert a.text_sha256() != JobRecord(verse_id="a", padas=["p", "r"]).text_sha256()


def test_defaults_and_precedence():
    d = load_defaults()
    assert d["steps"] == 10 and d["seed"] == 50 and d["speed"] == 0.9 and d["meter"] == "anuṣṭubh"
    assert d["voice"].endswith(".pt") and d["align_retries"] == 2
    rec = parse_record({"verse_id": "x", "padas": ["FIXTURE"], "render": {"steps": 12, "cfg": 2.5}})
    p = effective_params(rec, d, {"steps": 20, "seed": None})
    assert p["steps"] == 20 and p["cfg"] == 2.5 and p["seed"] == 50


def test_meter_precedence():
    d = load_defaults()
    rec = parse_record({"verse_id": "x", "padas": ["F"], "meter": "rec"})
    assert effective_params(rec, d, {"meter": "cli"})["meter"] == "rec"
    rec2 = parse_record({"verse_id": "x", "padas": ["F"]})
    assert effective_params(rec2, d, {"meter": "cli"})["meter"] == "cli"
    assert effective_params(rec2, d, {})["meter"] == d["meter"]


def test_params_hash():
    d = load_defaults()
    rec = parse_record({"verse_id": "x", "padas": ["F"]})
    p = effective_params(rec, d, {})
    h = params_hash(p)
    assert h == params_hash(dict(p))
    assert h != params_hash({**p, "steps": 16})
    assert h != params_hash({**p, "mp3_kbps": 96})
    assert ENGINE_VERSION == "1"
