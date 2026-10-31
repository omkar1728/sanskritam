import json
import pytest
from test_api import client, GITA  # noqa: F401

# FIXTURE verse text (test data only): words per line after stripping the danda
W0 = ["कर्मण्येवाधिकारस्ते", "मा", "फलेषु", "कदाचन"]
W1 = ["मा", "कर्मफलहेतुर्भूर्मा", "ते", "सङ्गोऽस्त्वकर्मणि"]


def words(only=None):
    out = [dict(line=l, index=i, text=t, meaning=f"m{l}{i}") for l, ws in enumerate([W0, W1]) for i, t in enumerate(ws)]
    return out if only is None else out[:only]


def test_put_get_meanings(client):
    client.post("/api/verses", json=GITA)
    assert client.get("/api/verses/bg-2-47").json()["meanings"] == {"words": [], "summary": None}
    body = {"words": words(), "summary": {"translation": "T", "explanation": "E"}}
    r = client.put("/api/verses/bg-2-47/meanings", json=body)
    assert r.status_code == 200, r.text
    m = client.get("/api/verses/bg-2-47").json()["meanings"]
    assert len(m["words"]) == 8 and m["words"][0] == dict(line=0, index=0, text=W0[0], meaning="m00", grammar=None, origin="user", reviewed=True)
    assert m["summary"] == dict(translation="T", explanation="E", origin="user", reviewed=True)
    assert client.get("/api/verses").json()[0]["meanings"] == m
    # replace: fewer words, machine origin defaults to unreviewed
    client.put("/api/verses/bg-2-47/meanings", json={"words": words(2), "origin": "machine"})
    m = client.get("/api/verses/bg-2-47").json()["meanings"]
    assert len(m["words"]) == 2 and m["summary"] is None and m["words"][0]["reviewed"] is False and m["words"][0]["origin"] == "machine"


def test_summary_only(client):
    client.post("/api/verses", json=GITA)
    assert client.put("/api/verses/bg-2-47/meanings", json={"summary": {"translation": "T"}}).status_code == 200
    m = client.get("/api/verses/bg-2-47").json()["meanings"]
    assert m["words"] == [] and m["summary"]["translation"] == "T" and m["summary"]["explanation"] is None


def test_mismatch_rejected_and_atomic(client):
    client.post("/api/verses", json=GITA)
    client.put("/api/verses/bg-2-47/meanings", json={"words": words(3)})
    bad_text = words(2) + [dict(line=0, index=2, text="wrong", meaning="x")]
    bad_pos = words(2) + [dict(line=0, index=9, text="x", meaning="x")]
    bad_line = [dict(line=5, index=0, text="x", meaning="x")]
    dup = words(2) + words(1)
    for b in (bad_text, bad_pos, bad_line, dup):
        r = client.put("/api/verses/bg-2-47/meanings", json={"words": b})
        assert r.status_code == 422 and r.json()["detail"], b
    assert client.put("/api/verses/bg-2-47/meanings", json={"words": [], "origin": "bogus"}).status_code == 422
    assert client.put("/api/verses/nope/meanings", json={"words": []}).status_code == 404
    assert len(client.get("/api/verses/bg-2-47").json()["meanings"]["words"]) == 3     # unchanged


def seed_entry(**mean):
    return dict(GITA, meanings=mean)


def grid(n0=4, n1=4):
    return [[dict(text=t, meaning="m") for t in W0[:n0]], [dict(text=t, meaning="m") for t in W1[:n1]]]


def test_seed_with_meanings(client, tmp_path):
    from backend.app import verses
    p = tmp_path / "s.json"
    p.write_text(json.dumps([seed_entry(words=grid(), summary={"translation": "T"})]))
    assert verses.load_seed(p) == 1
    m = client.get("/api/verses/bg-2-47").json()["meanings"]
    assert len(m["words"]) == 8 and {w["origin"] for w in m["words"]} == {"seed"} and all(w["reviewed"] for w in m["words"])
    assert m["summary"]["origin"] == "seed"
    assert verses.load_seed(p) == 1          # re-load is idempotent


def test_seed_count_mismatch_rejects_whole_file(client, tmp_path):
    from backend.app import verses
    other = dict(GITA, id="ok-1")
    for bad in (seed_entry(words=grid(3, 4)), seed_entry(words=grid()[:1]), seed_entry(summary={"translation": ""})):
        p = tmp_path / "s.json"; p.write_text(json.dumps([other, bad]))
        with pytest.raises(verses.VerseError): verses.load_seed(p)
        assert client.get("/api/verses/ok-1").status_code == 404
