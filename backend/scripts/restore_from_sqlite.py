"""Restore a backup/sloka_mirror.sqlite (made by backend.app.backup) into Postgres.

  uv run python -m backend.scripts.restore_from_sqlite --sqlite PATH [--database-url URL] [--yes]

Validates _meta and PRAGMA integrity_check first. Refuses if any target table has rows unless --yes, in which case
all tables are replaced inside ONE transaction. Creates the schema if missing, fixes the jobs identity sequence.
Only database rows are restored; S3 objects are not part of the mirror.
"""
import argparse, json, sqlite3, sys
from pathlib import Path
import psycopg
from backend.app import config as C, db, backup

def run(sqlite_path, database_url=None, yes=False) -> dict:
    path = Path(sqlite_path)
    if not path.exists(): raise SystemExit(f"no such file: {path}")
    src = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        if src.execute("PRAGMA integrity_check").fetchone()[0] != "ok": raise SystemExit("sqlite integrity_check failed")
        try: meta = dict(src.execute("SELECT key, value FROM _meta").fetchall())
        except sqlite3.Error: raise SystemExit("not a mirror file: _meta missing")
        counts = json.loads(meta.get("row_counts", "null") or "null")
        if not counts or any(t not in counts for t in backup.TABLES): raise SystemExit("invalid _meta row_counts")
        if int(meta["schema_version"]) > db.VERSION: raise SystemExit(f"mirror schema v{meta['schema_version']} newer than app v{db.VERSION}")
        for t in backup.TABLES:
            n = src.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0]
            if n != counts[t]: raise SystemExit(f"row count mismatch in {t}: {n} != {counts[t]}")
        kw = {"options": f"-c search_path={db.search_path}"} if db.search_path else {}
        with psycopg.connect(database_url or C.DATABASE_URL, **kw) as con:      # one transaction
            con.execute(db.SCHEMA)
            if not yes:
                full = [t for t in backup.TABLES if t != "schema_version" and con.execute(f'SELECT 1 FROM "{t}" LIMIT 1').fetchone()]
                if full: raise SystemExit(f"refusing: target tables not empty ({', '.join(full)}); use --yes to replace")
            con.execute("TRUNCATE " + ", ".join(f'"{t}"' for t in backup.TABLES) + " CASCADE")
            for t in backup.TABLES:
                tcols = con.execute("SELECT column_name, data_type FROM information_schema.columns WHERE table_schema=current_schema()"
                                    " AND table_name=%s ORDER BY ordinal_position", (t,)).fetchall()
                scols = [r[1] for r in src.execute(f'PRAGMA table_info("{t}")')]
                tcols = [(c, ty) for c, ty in tcols if c in scols]      # columns added later in Postgres take defaults
                sel = ", ".join(f'"{c}"' for c, _ in tcols)
                ph = ", ".join("%s" + ("" if ty in ("integer", "bigint", "smallint", "real", "double precision") else f"::{ty}")
                               for _, ty in tcols)
                ov = " OVERRIDING SYSTEM VALUE" if t == "jobs" else ""
                with con.cursor() as cur:
                    for row in src.execute(f'SELECT {sel} FROM "{t}"'):
                        row = [bool(v) if ty == "boolean" and v is not None else v for v, (_, ty) in zip(row, tcols)]
                        cur.execute(f'INSERT INTO "{t}"({sel}){ov} VALUES({ph})', row)
            con.execute("SELECT setval(pg_get_serial_sequence('jobs','id'), greatest((SELECT coalesce(max(id),0) FROM jobs), 1),"
                        " (SELECT count(*) > 0 FROM jobs))")
        return counts
    finally:
        src.close()

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sqlite", required=True); ap.add_argument("--database-url"); ap.add_argument("--yes", action="store_true")
    a = ap.parse_args(argv)
    counts = run(a.sqlite, a.database_url, a.yes)
    for t, n in counts.items(): print(f"{t:16}{n}")
    print("restored.")

if __name__ == "__main__":
    main()
