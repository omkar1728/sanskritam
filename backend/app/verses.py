"""Verse validation and seed loading. Sources are mandatory; the app never invents text or citations."""
import json
from pathlib import Path
import psycopg.errors
from . import db

class VerseError(ValueError): ...

def validate(v: dict) -> dict:
    if not isinstance(v, dict):
        raise VerseError("verse must be an object")
    vid = str(v.get("id") or "").strip()
    text = v.get("text")
    src = v.get("source") or {}
    if isinstance(text, str):
        text = [l for l in text.splitlines() if l.strip()]
    if not isinstance(text, list) or not text or not all(isinstance(l, str) and l.strip() for l in text):
        raise VerseError(f"{vid or '?'}: 'text' must be a non-empty list of lines")
    for f in ("work", "reference"):
        if not str(src.get(f) or "").strip():
            raise VerseError(f"{vid or '?'}: source.{f} is required")
    if not vid:
        raise VerseError("id is required")
    lines = [l.strip() for l in text]
    meanings = _seed_meanings(vid, lines, v.get("meanings"))
    return {"id": vid, "meanings": meanings, "title": (v.get("title") or f"{src['work']} {src['reference']}").strip(),
            "text": [l.strip() for l in text], "source_work": src["work"].strip(),
            "source_reference": src["reference"].strip(), "source_url": src.get("url"),
            "source_edition": src.get("edition"), "notes": v.get("notes"), "meter_hint": v.get("meter_hint")}

def word_grid(lines: list[str]) -> list[list[str]]:
    """Words per line as the player splits them: trailing dandas stripped, then whitespace split."""
    return [l.strip().rstrip("।॥|").strip().split() for l in lines]

def _seed_meanings(vid, lines, m):
    if m is None: return None
    if not isinstance(m, dict): raise VerseError(f"{vid}: 'meanings' must be an object")
    grid = word_grid(lines)
    words = []
    if m.get("words") is not None:
        ws = m["words"]
        if not isinstance(ws, list) or len(ws) != len(grid):
            raise VerseError(f"{vid}: meanings.words must have one list per line ({len(grid)})")
        for li, (got, want) in enumerate(zip(ws, grid)):
            if not isinstance(got, list) or len(got) != len(want):
                raise VerseError(f"{vid}: line {li} has {len(want)} words but meanings has "
                                 f"{len(got) if isinstance(got, list) else 'a non-list'}")
            for wi, w in enumerate(got):
                if not isinstance(w, dict) or w.get("text") != want[wi] or not str(w.get("meaning") or "").strip():
                    raise VerseError(f"{vid}: line {li} word {wi} must have text '{want[wi]}' and a meaning")
                words.append({"line": li, "index": wi, "text": (w or {}).get("text"), "meaning": (w or {}).get("meaning"),
                              "grammar": (w or {}).get("grammar")})
    sm = m.get("summary")
    if sm is not None and (not isinstance(sm, dict) or not str(sm.get("translation") or "").strip()):
        raise VerseError(f"{vid}: meanings.summary needs a translation")
    return {"words": words, "summary": sm}

def padas(lines: list[str]) -> list[str]:
    """Lines -> synthesis segments (trailing dandas stripped)."""
    return [l.strip().rstrip("।॥|").strip() for l in lines if l.strip().rstrip("।॥|").strip()]

def insert(v: dict, origin: str, replace=False):
    row = validate(v)
    sql = ("INSERT INTO verses(id,title,text,source_work,source_reference,source_url,source_edition,notes,meter_hint,origin)"
           " VALUES(?,?,?::jsonb,?,?,?,?,?,?,?)")
    if replace:
        sql += (" ON CONFLICT (id) DO UPDATE SET title=EXCLUDED.title, text=EXCLUDED.text, source_work=EXCLUDED.source_work,"
                " source_reference=EXCLUDED.source_reference, source_url=EXCLUDED.source_url,"
                " source_edition=EXCLUDED.source_edition, notes=EXCLUDED.notes, meter_hint=EXCLUDED.meter_hint,"
                " origin=EXCLUDED.origin")
    try:
        with db.tx():
            db.x(sql, (row["id"], row["title"], json.dumps(row["text"], ensure_ascii=False), row["source_work"],
                       row["source_reference"], row["source_url"], row["source_edition"], row["notes"], row["meter_hint"], origin))
            if row["meanings"]:
                set_meanings(row["id"], row["meanings"]["words"], row["meanings"]["summary"], "seed", True)
    except psycopg.errors.UniqueViolation:
        raise VerseError(f"duplicate verse id '{row['id']}'")
    return row["id"]

class MeaningsError(ValueError): ...

def _need_str(v, what, optional=False):
    if v is None and optional: return None
    if not isinstance(v, str) or not v.strip(): raise MeaningsError(f"{what} must be a non-empty string")
    return v.strip() if what != "text" else v

def set_meanings(verse_id: str, words: list[dict], summary: dict | None, origin: str, reviewed: bool):
    """Replace all word meanings and the summary of a verse, transactionally. Raises KeyError (no verse) / MeaningsError."""
    if origin not in ("seed", "user", "machine"): raise MeaningsError("origin must be seed, user or machine")
    r = db.q1("SELECT text FROM verses WHERE id=?", (verse_id,))
    if not r: raise KeyError("verse")
    grid = word_grid(r["text"])
    seen = set(); rows = []
    for w in words or []:
        li, wi = w.get("line"), w.get("index")
        if not (isinstance(li, int) and isinstance(wi, int) and 0 <= li < len(grid) and 0 <= wi < len(grid[li])):
            raise MeaningsError(f"no word at line {li}, index {wi}")
        if (li, wi) in seen: raise MeaningsError(f"duplicate word at line {li}, index {wi}")
        seen.add((li, wi))
        if w.get("text") != grid[li][wi]:
            raise MeaningsError(f"text mismatch at line {li}, index {wi}: expected '{grid[li][wi]}', got '{w.get('text')}'")
        rows.append((verse_id, li, wi, w["text"], _need_str(w.get("meaning"), f"meaning at line {li}, index {wi}"),
                     (w.get("grammar") or None), origin, reviewed))
    if summary is not None:
        tr = _need_str(summary.get("translation"), "summary.translation")
        ex = summary.get("explanation") or None
    with db.tx():
        db.x("DELETE FROM word_meanings WHERE verse_id=?", (verse_id,))
        db.x("DELETE FROM verse_summaries WHERE verse_id=?", (verse_id,))
        for r_ in rows:
            db.x("INSERT INTO word_meanings(verse_id,line_idx,word_idx,word_text,meaning,grammar,origin,reviewed)"
                 " VALUES(?,?,?,?,?,?,?,?)", r_)
        if summary is not None:
            db.x("INSERT INTO verse_summaries(verse_id,translation,explanation,origin,reviewed) VALUES(?,?,?,?,?)",
                 (verse_id, tr, ex, origin, reviewed))

def get_meanings(verse_id: str) -> dict:
    ws = db.q("SELECT line_idx line, word_idx index, word_text text, meaning, grammar, origin, reviewed "
              "FROM word_meanings WHERE verse_id=? ORDER BY line_idx, word_idx", (verse_id,))
    sm = db.q1("SELECT translation, explanation, origin, reviewed FROM verse_summaries WHERE verse_id=?", (verse_id,))
    return {"words": ws, "summary": sm}

def load_seed(path: Path) -> int:
    """All-or-nothing: any invalid or duplicate entry rejects the whole file."""
    if not path.exists():
        return 0
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise VerseError("seed file must be a JSON list")
    rows = [validate(v) for v in data]
    ids = [r["id"] for r in rows]
    dup = {i for i in ids if ids.count(i) > 1}
    if dup:
        raise VerseError(f"duplicate ids in seed: {sorted(dup)}")
    with db.tx():
        for v in data:
            insert(v, "seed", replace=True)
    return len(rows)

def present(r: dict) -> dict:
    r = dict(r)
    if isinstance(r["text"], str): r["text"] = json.loads(r["text"])
    r["source"] = {"work": r.pop("source_work"), "reference": r.pop("source_reference"),
                   "url": r.pop("source_url"), "edition": r.pop("source_edition")}
    return r
