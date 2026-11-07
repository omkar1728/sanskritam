"""Read-only Epics browser API (data imported by epics_import)."""
from fastapi import APIRouter, HTTPException
from . import db

router = APIRouter(prefix="/api/epics")
def _lab(i, n, ns, bl, bls, cl, cls):
    return {"id": i, "name": n, "name_sa": ns, "book_label": bl, "book_label_sa": bls, "chapter_label": cl, "chapter_label_sa": cls}

EPICS = {
    "ramayana": _lab("ramayana", "Ramayana", "रामायणम्", "Kanda", "काण्ड", "Sarga", "सर्ग"),
    "mahabharata": _lab("mahabharata", "Mahabharata", "महाभारतम्", "Parvan", "पर्व", "Adhyaya", "अध्याय"),
    "harivamsha": _lab("harivamsha", "Harivamsha", "हरिवंशम्", "Parvan", "पर्व", "Adhyaya", "अध्याय"),
}

def _epic(e):
    if e not in EPICS: raise HTTPException(404, "unknown epic")

def _kanda_row(e, n):
    r = q1_kanda(e, n)
    if not r: raise HTTPException(404, "unknown kanda")
    return r

def q1_kanda(e, n):
    return db.q1("SELECT data->'kanda' AS k FROM epic_verses WHERE epic=? AND kanda=? ORDER BY sarga, seq LIMIT 1", (e, n))

@router.get("")
def list_epics():
    out = []
    for e, meta in EPICS.items():
        kc = db.q1("SELECT count(DISTINCT kanda) c FROM epic_sargas WHERE epic=?", (e,))["c"]
        vc = db.q1("SELECT count(*) c FROM epic_verses WHERE epic=?", (e,))["c"]
        out.append({**meta, "kanda_count": kc, "verse_count": vc})
    return out

@router.get("/{epic}/kandas")
def kandas(epic: str):
    _epic(epic)
    # counts from the (epic,kanda,sarga,seq) index; names from one verse per kanda (avoids detoasting every doc)
    rows = db.q("""SELECT k.kanda AS number, k.sarga_count, k.verse_count,
                   n.k->>'name_sa' AS name_sa, n.k->>'name_en' AS name_en
                   FROM (SELECT kanda, count(DISTINCT sarga) AS sarga_count, count(*) AS verse_count
                         FROM epic_verses WHERE epic=? GROUP BY kanda) k
                   LEFT JOIN LATERAL (SELECT v.data->'kanda' AS k FROM epic_verses v
                         WHERE v.epic=? AND v.kanda=k.kanda ORDER BY v.sarga, v.seq LIMIT 1) n ON true
                   ORDER BY k.kanda""", (epic, epic))
    return rows

@router.get("/{epic}/kandas/{n}/sargas")
def sargas(epic: str, n: int):
    _epic(epic)
    rows = db.q("""SELECT s.sarga, s.data->>'title_hi_from_in' AS title_hi, COALESCE(s.data->>'title_en_from_in', s.data->>'title_en') AS title_en,
                   s.data->>'title_sa' AS title_sa,
                   COALESCE(c.c, 0) AS verse_count,
                   COALESCE(s.data->>'layer', 'critical') AS layer,
                   COALESCE((s.data->>'adhyaya_display')::int, s.sarga) AS adhyaya_display
                   FROM epic_sargas s
                   LEFT JOIN (SELECT sarga, count(*) AS c FROM epic_verses WHERE epic=? AND kanda=? GROUP BY sarga) c
                     ON c.sarga=s.sarga
                   WHERE s.epic=? AND s.kanda=? ORDER BY s.sarga""", (epic, n, epic, n))
    if not rows: raise HTTPException(404, "unknown kanda")
    return rows

@router.get("/{epic}/kandas/{n}/sargas/{s}")
def sarga(epic: str, n: int, s: int):
    _epic(epic)
    meta = db.q1("SELECT data FROM epic_sargas WHERE epic=? AND kanda=? AND sarga=?", (epic, n, s))
    if not meta: raise HTTPException(404, "unknown sarga")
    verses = [r["data"] for r in db.q("SELECT data FROM epic_verses WHERE epic=? AND kanda=? AND sarga=? ORDER BY seq", (epic, n, s))]
    if verses: kd = verses[0]["kanda"]
    else:
        r = q1_kanda(epic, n)
        kd = r["k"] if r and r["k"] else {"number": n, "name_sa": None, "name_en": None}
    prev = db.q1("SELECT max(sarga) s FROM epic_sargas WHERE epic=? AND kanda=? AND sarga<?", (epic, n, s))["s"]
    nxt = db.q1("SELECT min(sarga) s FROM epic_sargas WHERE epic=? AND kanda=? AND sarga>?", (epic, n, s))["s"]
    return {"kanda": {"number": kd["number"], "name_sa": kd.get("name_sa"), "name_en": kd.get("name_en")},
            "sarga": s, "layer": meta["data"].get("layer") or "critical", "meta": meta["data"], "verses": verses,
            "prev": {"sarga": prev} if prev is not None else None,
            "next": {"sarga": nxt} if nxt is not None else None}
