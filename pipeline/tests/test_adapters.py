"""FIXTURE tests. Real text only for baala-001-001; other verses use placeholder padas."""
import json
from types import SimpleNamespace

from pipeline.adapters import iter_records
from pipeline.adapters import epic_json, jsonl, txt

REAL = ["तपःस्वाध्यायनिरतं तपस्वी वाग्विदां वरम्", "नारदं परिपप्रच्छ वाल्मीकिर्मुनिपुंगवम्"]  # baala-001-001 critical_smith


def _verse(root, kanda, sarga, n, text, vid=None):
    d = root / kanda / f"sarga_{sarga:03d}"
    d.mkdir(parents=True, exist_ok=True)
    doc = {"id": vid or f"{kanda}-{sarga:03d}-{n:03d}", "sarga": sarga, "seq_in_sarga": n}
    if text is not None:
        doc["text"] = text
    (d / f"verse_{n:03d}.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")


def test_epic_json_fallback(tmp_path):  # FIXTURE tree
    _verse(tmp_path, "baala", 1, 1, {"critical_smith": {"lines": REAL}, "vulgate_net": {"lines": ["FIXTURE net"]}})
    _verse(tmp_path, "baala", 1, 2, {"critical_smith": {"lines": []}, "vulgate_net": {"lines": ["FIXTURE net pada"]},
                                     "vulgate_in": {"lines": ["FIXTURE in pada"]}})
    _verse(tmp_path, "baala", 1, 3, {"vulgate_in": {"lines": ["FIXTURE in only"]},
                                     "vulgate_gitapress": {"lines": ["FIXTURE OCR never"]}})
    _verse(tmp_path, "baala", 1, 4, {"vulgate_gitapress": {"lines": ["FIXTURE OCR never"]}})
    _verse(tmp_path, "ayodhya", 1, 1, None)  # no text key: skipped
    _verse(tmp_path, "ayodhya", 1, 2, {"critical_smith": {"lines": ["FIXTURE ayodhya pada"]}})
    bad, skip = [], []
    recs = list(epic_json.iter_records(tmp_path, lambda *a: bad.append(a), lambda *a: skip.append(a)))
    by = {r.verse_id: r for r in recs}
    assert list(by) == ["baala-001-001", "baala-001-002", "baala-001-003", "ayodhya-001-002"]
    assert by["baala-001-001"].padas == REAL and not by["baala-001-001"].text_fallback
    assert by["baala-001-001"].book == "baala" and by["baala-001-001"].chapter == 1 and by["baala-001-001"].seq == 1
    assert by["baala-001-002"].text_variant == "vulgate_net" and by["baala-001-002"].text_fallback
    assert by["baala-001-003"].text_variant == "vulgate_in" and by["baala-001-003"].text_fallback
    assert [b[1:] for b in bad] == [("baala-001-004", "no_text")]
    assert len(skip) == 1


def test_jsonl_roundtrip_and_invalid(tmp_path):
    p = tmp_path / "a.jsonl"
    lines = [json.dumps({"verse_id": "baala-001-001", "padas": REAL}, ensure_ascii=False),
             "not json",
             json.dumps({"verse_id": "BAD", "padas": ["x"]}),
             json.dumps({"verse_id": "fx-1", "padas": ["FIXTURE pada one"], "extra_note": "FIXTURE"}),
             ""]
    p.write_text("\n".join(lines), encoding="utf-8")
    bad = []
    recs = list(jsonl.iter_records([str(tmp_path / "*.jsonl")], lambda *a: bad.append(a)))
    assert [r.verse_id for r in recs] == ["baala-001-001", "fx-1"]
    assert recs[1].extra == {"extra_note": "FIXTURE"}
    assert len(bad) == 2


def test_txt_adapter(tmp_path):
    (tmp_path / "v.txt").write_text(
        "# id: baala-001-001 meter: anuṣṭubh\n" + "\n".join(REAL) + "\n\n"
        "# id: fx-2\nFIXTURE pada one\nFIXTURE pada two\n\n"
        "# id: bad id\nFIXTURE\n", encoding="utf-8")
    bad = []
    recs = list(txt.iter_records(tmp_path, lambda *a: bad.append(a)))
    assert [r.verse_id for r in recs] == ["baala-001-001", "fx-2"]
    assert recs[0].meter == "anuṣṭubh" and recs[0].book == "baala" and recs[0].chapter == 1 and recs[0].seq == 1
    assert recs[0].padas == REAL and len(bad) == 1


def test_same_text_across_adapters(tmp_path):
    root = tmp_path / "tree"
    _verse(root, "baala", 1, 1, {"critical_smith": {"lines": REAL}})
    j = tmp_path / "x.jsonl"
    j.write_text(json.dumps({"verse_id": "baala-001-001", "padas": REAL}, ensure_ascii=False), encoding="utf-8")
    t = tmp_path / "t"
    t.mkdir()
    (t / "a.txt").write_text("# id: baala-001-001\n" + "\n".join(REAL), encoding="utf-8")
    shas = set()
    for args in (SimpleNamespace(input_epic_json=str(root)), SimpleNamespace(input=[str(j)]),
                 SimpleNamespace(input_txt=str(t))):
        (r,) = list(iter_records(args))
        shas.add(r.text_sha256())
    assert len(shas) == 1
