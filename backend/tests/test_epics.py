"""Epics import + API tests. All data below is a FIXTURE (placeholder text, not real verses)."""
import json
import pytest
from fastapi.testclient import TestClient
from backend.app import db, epics_import


def _write(root, key, num, sargas):
    """sargas: {sarga_no: n_verses}. FIXTURE content only."""
    for s, n in sargas.items():
        d = root / key / f"sarga_{s:03d}"; d.mkdir(parents=True, exist_ok=True)
        meta = {"kanda": num, "sarga": s, "FIXTURE": True}
        if s != 3: meta.update(title_hi_from_in=f"FIXTURE hi {s}", title_en_from_in=f"FIXTURE en {s}")
        (d / "_sarga.json").write_text(json.dumps(meta, ensure_ascii=False))
        for i in range(1, n + 1):
            v = {"id": f"{key}-{s:03d}-{i:03d}", "kanda": {"number": num, "name_sa": f"FIXTURE-sa-{key}", "name_en": f"FIXTURE {key}"},
                 "sarga": s, "seq_in_sarga": i, "kind": "critical", "text": {"critical_smith": {"lines": ["FIXTURE line"]}}}
            (d / f"verse_{i:03d}.json").write_text(json.dumps(v, ensure_ascii=False))


@pytest.fixture()
def src(tmp_path):
    root = tmp_path / "unified"
    _write(root, "baala", 1, {1: 3, 2: 2, 3: 1})
    _write(root, "ayodhya", 2, {1: 2})
    (root / "baala" / "_report.json").write_text("{}")
    return root


@pytest.fixture()
def client(pg, mem_storage):
    db.init()
    from backend.app.main import app
    return TestClient(app)


def test_import_counts_idempotent_and_delete(client, src, capsys):
    t = epics_import.run(src)
    assert t == {"sargas": [4, 0, 0], "verses": [8, 0, 0]}
    assert db.q1("SELECT count(*) c FROM epic_verses")["c"] == 8
    t = epics_import.run(src)
    assert t == {"sargas": [0, 0, 0], "verses": [0, 0, 0]}
    assert db.q1("SELECT count(*) c FROM epic_verses")["c"] == 8
    (src / "baala" / "sarga_001" / "verse_003.json").unlink()
    p = src / "baala" / "sarga_002" / "verse_001.json"
    d = json.loads(p.read_text()); d["kind"] = "vulgate_only"; p.write_text(json.dumps(d))
    t = epics_import.run(src)
    assert t == {"sargas": [0, 0, 0], "verses": [0, 1, 1]}
    assert db.q1("SELECT kind FROM epic_verses WHERE id='baala-002-001'")["kind"] == "vulgate_only"
    assert db.q1("SELECT count(*) c FROM epic_verses")["c"] == 7


def test_malformed_fails_with_path(client, src):
    bad = src / "baala" / "sarga_001" / "verse_001.json"
    bad.write_text("{not json")
    with pytest.raises(SystemExit) as e:
        epics_import.run(src)
    assert str(bad) in str(e.value)


def test_endpoints_empty(client):
    assert client.get("/api/epics").json() == [
        {"id": "ramayana", "name": "Ramayana", "name_sa": "रामायणम्", "book_label": "Kanda", "book_label_sa": "काण्ड",
         "chapter_label": "Sarga", "chapter_label_sa": "सर्ग", "kanda_count": 0, "verse_count": 0},
        {"id": "mahabharata", "name": "Mahabharata", "name_sa": "महाभारतम्", "book_label": "Parvan", "book_label_sa": "पर्व",
         "chapter_label": "Adhyaya", "chapter_label_sa": "अध्याय", "kanda_count": 0, "verse_count": 0},
        {"id": "harivamsha", "name": "Harivamsha", "name_sa": "हरिवंशम्", "book_label": "Parvan", "book_label_sa": "पर्व",
         "chapter_label": "Adhyaya", "chapter_label_sa": "अध्याय", "kanda_count": 0, "verse_count": 0}]
    assert client.get("/api/epics/ramayana/kandas").json() == []
    assert client.get("/api/epics/nope/kandas").status_code == 404
    assert client.get("/api/epics/ramayana/kandas/1/sargas").status_code == 404


def test_endpoints(client, src):
    epics_import.run(src)
    e = client.get("/api/epics").json()[0]
    assert (e["kanda_count"], e["verse_count"]) == (2, 8)
    ks = client.get("/api/epics/ramayana/kandas").json()
    assert ks[0] == {"number": 1, "name_sa": "FIXTURE-sa-baala", "name_en": "FIXTURE baala", "sarga_count": 3, "verse_count": 6}
    assert [k["number"] for k in ks] == [1, 2]
    ss = client.get("/api/epics/ramayana/kandas/1/sargas").json()
    assert ss[0] == {"sarga": 1, "title_hi": "FIXTURE hi 1", "title_en": "FIXTURE en 1", "title_sa": None,
                     "verse_count": 3, "layer": "critical", "adhyaya_display": 1}
    assert ss[2]["title_hi"] is None and ss[2]["verse_count"] == 1
    r = client.get("/api/epics/ramayana/kandas/1/sargas/2").json()
    assert r["kanda"] == {"number": 1, "name_sa": "FIXTURE-sa-baala", "name_en": "FIXTURE baala"}
    assert r["sarga"] == 2 and r["meta"]["FIXTURE"] is True and r["layer"] == "critical"
    assert [v["seq_in_sarga"] for v in r["verses"]] == [1, 2]
    assert r["verses"][0]["text"]["critical_smith"]["lines"] == ["FIXTURE line"]
    assert r["prev"] == {"sarga": 1} and r["next"] == {"sarga": 3}
    assert client.get("/api/epics/ramayana/kandas/1/sargas/1").json()["prev"] is None
    assert client.get("/api/epics/ramayana/kandas/1/sargas/3").json()["next"] is None
    assert client.get("/api/epics/ramayana/kandas/1/sargas/9").status_code == 404
    assert client.get("/api/epics/ramayana/kandas/9/sargas").status_code == 404


# ---------------------------------------------------------------- Mahabharata / Harivamsha (FIXTURES only)

def _mbh_fixture(root):
    """FIXTURE: adi has CE adhyaya 1 (2 verses), southern-only adhyaya 24 (1 verse); 1 unplaced supplement passage."""
    adi = root / "adi"
    def verse(d, vid, adh, seq, kind):
        d.mkdir(parents=True, exist_ok=True)
        (d / f"verse_{seq:03d}.json").write_text(json.dumps({
            "id": vid, "epic": "mahabharata", "parvan": {"number": 1, "key": "adi", "name_en": "Adi"},
            "adhyaya": adh, "seq_in_adhyaya": seq, "kind": kind, "text": {"FIXTURE": "placeholder"}}))
    d = adi / "adhyaya_001"
    verse(d, "adi-001-001", 1, 1, "critical"); verse(d, "adi-001-002", 1, 2, "critical")
    (d / "_adhyaya.json").write_text(json.dumps({
        "parvan": "adi", "id": "adi-001", "kind": "critical", "critical_adhyaya": 1, "FIXTURE": True,
        "southern_chapters": [{"adhyaya": 1, "head": "FIXTURE head 1", "topic": "FIXTURE topic 1"}],
        "supplements_unplaced_verse": []}))
    d = adi / "southern_only_adhyaya_024"
    verse(d, "adi-s024-001", None, 1, "southern_only")
    (d / "_adhyaya.json").write_text(json.dumps({
        "parvan": "adi", "id": "adi-s024", "kind": "southern_only", "critical_adhyaya": None, "FIXTURE": True,
        "southern_chapters": [{"adhyaya": 24, "head": "FIXTURE head 24"}]}))
    (adi / "_report.json").write_text("{}")
    sp = root / "supplements"; sp.mkdir()
    (sp / "01.json").write_text(json.dumps({
        "parvan": "adi", "parvan_number": 1, "FIXTURE": True,
        "unplaced_passages": [{"passage_id": "01*0001", "kind": "star_passage",
                               "lines": [{"id": "01*0001_01", "text": "FIXTURE line"}], "placement": "unplaced"}]}))
    return root


@pytest.fixture()
def mbh(tmp_path):
    return _mbh_fixture(tmp_path / "unified")


def test_mbh_dry_run_writes_nothing(client, mbh):
    r = epics_import.run(mbh, "mahabharata", dry=True)
    assert r["verses"] == 4 and r["sargas"] == 3 and r["unplaced_passages"] == 1
    assert db.q1("SELECT count(*) c FROM epic_verses")["c"] == 0


def test_mbh_import_keys_normalisation_idempotent_delete(client, mbh):
    t = epics_import.run(mbh, "mahabharata")
    assert t == {"sargas": [3, 0, 0], "verses": [4, 0, 0]}
    rows = {r["sarga"]: r for r in db.q("SELECT sarga FROM epic_sargas WHERE epic='mahabharata' AND kanda=1")}
    assert sorted(rows) == [0, 1, 1024]
    v = db.q1("SELECT data, kind, seq FROM epic_verses WHERE id='adi-001-002'")["data"]
    assert v["kanda"] == {"number": 1, "name_sa": "आदिपर्व", "name_en": "Adi", "key": "adi"}
    assert (v["sarga"], v["seq_in_sarga"], v["layer"], v["adhyaya_display"]) == (1, 2, "critical", 1)
    assert v["seq_in_adhyaya"] == 2 and v["parvan"]["key"] == "adi" and v["text"] == {"FIXTURE": "placeholder"}
    so = db.q1("SELECT data, sarga FROM epic_verses WHERE id='adi-s024-001'")
    assert so["sarga"] == 1024 and so["data"]["layer"] == "southern_only" and so["data"]["adhyaya_display"] == 24
    sup = db.q1("SELECT data, sarga, kind FROM epic_verses WHERE id='supp-01-01*0001'")
    assert sup["sarga"] == 0 and sup["kind"] == "supplement" and sup["data"]["layer"] == "supplements_unplaced"
    sd = db.q1("SELECT data FROM epic_sargas WHERE epic='mahabharata' AND kanda=1 AND sarga=1")["data"]
    assert sd["FIXTURE"] and sd["layer"] == "critical" and sd["title_sa"] == "FIXTURE topic 1" and sd["title_en"] is None
    assert db.q1("SELECT data FROM epic_sargas WHERE kanda=1 AND sarga=1024")["data"]["title_sa"] == "FIXTURE head 24"
    assert epics_import.run(mbh, "mahabharata") == {"sargas": [0, 0, 0], "verses": [0, 0, 0]}
    (mbh / "adi" / "adhyaya_001" / "verse_002.json").unlink()
    p = mbh / "adi" / "southern_only_adhyaya_024" / "verse_001.json"
    d = json.loads(p.read_text()); d["text"] = {"FIXTURE": "changed"}; p.write_text(json.dumps(d))
    assert epics_import.run(mbh, "mahabharata") == {"sargas": [0, 0, 0], "verses": [0, 1, 1]}
    (mbh / "supplements" / "01.json").unlink()
    t = epics_import.run(mbh, "mahabharata")
    assert t == {"sargas": [0, 0, 1], "verses": [0, 0, 1]}
    assert db.q1("SELECT count(*) c FROM epic_verses")["c"] == 2


def test_mbh_api_shapes(client, mbh):
    epics_import.run(mbh, "mahabharata")
    e = {x["id"]: x for x in client.get("/api/epics").json()}
    assert (e["mahabharata"]["kanda_count"], e["mahabharata"]["verse_count"]) == (1, 4)
    assert e["ramayana"]["verse_count"] == 0
    ks = client.get("/api/epics/mahabharata/kandas").json()
    assert ks == [{"number": 1, "name_sa": "आदिपर्व", "name_en": "Adi", "sarga_count": 3, "verse_count": 4}]
    ss = client.get("/api/epics/mahabharata/kandas/1/sargas").json()
    assert [(s["sarga"], s["layer"], s["adhyaya_display"], s["verse_count"]) for s in ss] == [
        (0, "supplements_unplaced", 0, 1), (1, "critical", 1, 2), (1024, "southern_only", 24, 1)]
    assert ss[1]["title_sa"] == "FIXTURE topic 1" and ss[1]["title_hi"] is None
    r = client.get("/api/epics/mahabharata/kandas/1/sargas/1024").json()
    assert r["layer"] == "southern_only" and r["kanda"]["name_sa"] == "आदिपर्व"
    assert r["prev"] == {"sarga": 1} and r["next"] is None and len(r["verses"]) == 1
    assert client.get("/api/epics/mahabharata/kandas/1/sargas/1").json()["prev"] == {"sarga": 0}


def test_mbh_duplicate_id_and_malformed(client, mbh):
    d = mbh / "adi" / "adhyaya_001"
    v = json.loads((d / "verse_001.json").read_text())
    s = mbh / "adi" / "southern_only_adhyaya_024"
    v2 = dict(v); (s / "verse_002.json").write_text(json.dumps(v2))
    with pytest.raises(SystemExit) as e:
        epics_import.run(mbh, "mahabharata", dry=True)
    assert "duplicate verse id" in str(e.value)
    (s / "verse_002.json").write_text("{bad")
    with pytest.raises(SystemExit) as e:
        epics_import.run(mbh, "mahabharata")
    assert str(s / "verse_002.json") in str(e.value)
    assert db.q1("SELECT count(*) c FROM epic_verses")["c"] == 0   # transaction rolled back


def test_harivamsha_import(client, tmp_path):
    root = tmp_path / "hv"   # FIXTURE
    for folder, adh, n in (("parvan_1", "adhyaya_001", 2), ("front", "adhyaya_000", 1), ("appendix_1", "adhyaya_none", 1)):
        d = root / folder / adh; d.mkdir(parents=True)
        for i in range(1, n + 1):
            (d / f"unit_{i:04d}.json").write_text(json.dumps({"id": f"FIXTURE-{folder}-{i}", "layer": "harivamsha",
                                                              "kind": "verse", "seq_in_dir": i, "text": {}}))
    t = epics_import.run(root, "harivamsha")
    assert t == {"sargas": [3, 0, 0], "verses": [4, 0, 0]}
    ks = client.get("/api/epics/harivamsha/kandas").json()
    assert [(k["number"], k["name_sa"], k["verse_count"]) for k in ks] == [
        (0, "प्रारम्भः", 1), (1, "हरिवंशपर्व", 2), (99, "परिशिष्टम् १", 1)]
    assert epics_import.run(root, "harivamsha") == {"sargas": [0, 0, 0], "verses": [0, 0, 0]}
