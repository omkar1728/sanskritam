"""Postgres adapter (read-only, server-side cursor, chunks of 5000). psycopg is imported lazily.

Two modes:
- pg_table: `epic_verses` (columns id, epic, kanda int, sarga, seq, kind, data jsonb = the verse JSON) with
  pg_variant (default critical_smith); same fallback rule as epic_json (D8/D23).
- pg_query: path to a .sql file whose rows have JobRecord columns (verse_id, padas as text[] or json, ...).
"""
from __future__ import annotations

import json
from pathlib import Path

from ..schema import parse_record
from .epic_json import pick_variant

CHUNK = 5000
KANDA_KEYS = {1: "baala", 2: "ayodhya", 3: "aranya", 4: "kishkindha", 5: "sundara", 6: "yuddha", 7: "uttara"}


def _connect(dsn: str):
    try:
        import psycopg
    except ImportError as e:
        raise RuntimeError("the Postgres adapter needs the 'psycopg' package") from e
    con = psycopg.connect(dsn)
    con.read_only = True
    return con


def iter_records(dsn: str, table: str | None = None, variant: str | None = None, query: str | None = None,
                 on_invalid=None, epic: str = "ramayana"):
    if not table and not query:
        raise ValueError("postgres adapter needs pg_table or pg_query")
    con = _connect(dsn)
    try:
        if table:
            if table != "epic_verses":
                raise ValueError("only --pg-table epic_verses is supported; use --pg-query for other tables")
            sql = "SELECT id, kanda, sarga, seq, data->'text' AS text FROM epic_verses WHERE epic = %s ORDER BY kanda, sarga, seq"
            params = (epic,)
        else:
            sql = Path(query).read_text(encoding="utf-8")
            params = None
        with con.cursor(name="pipeline_read") as cur:
            cur.itersize = CHUNK
            cur.execute(sql, params)
            cols = [c.name for c in cur.description]
            while True:
                rows = cur.fetchmany(CHUNK)
                if not rows:
                    break
                for row in rows:
                    r = dict(zip(cols, row))
                    try:
                        if table:
                            v, lines, fb = pick_variant(r["text"] or {}, variant or "critical_smith")
                            if v is None:
                                if on_invalid:
                                    on_invalid("postgres", r["id"], "no_text")
                                continue
                            d = {"verse_id": r["id"], "work": epic, "book": KANDA_KEYS.get(r["kanda"], str(r["kanda"])),
                                 "chapter": r["sarga"], "seq": r["seq"], "text_variant": v,
                                 "text_fallback": fb, "padas": list(lines)}
                        else:
                            d = {k: (json.loads(x) if k in ("padas", "render") and isinstance(x, str) else x)
                                 for k, x in r.items()}
                        yield parse_record(d)
                    except ValueError as e:
                        if on_invalid:
                            on_invalid("postgres", r.get("id") or r.get("verse_id"), str(e))
    finally:
        con.close()
