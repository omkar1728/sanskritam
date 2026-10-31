"""Continuous Postgres -> SQLite mirror (plain-file copy of every app table).

Mirrors verses, meanings, summaries, meters, voices, jobs, assets (object-storage KEYS only), settings and
schema_version. S3 / MinIO objects themselves (mp3/wav/alignment files) are NOT mirrored; back those up separately.

Every BACKUP_INTERVAL_S seconds a daemon thread reads all tables in one REPEATABLE READ transaction, fingerprints the
rows and, only if the fingerprint changed, writes a full snapshot to a temp file (integrity_check + fsync) and
atomically os.replace()s it onto BACKUP_SQLITE_PATH. The previous file is hard-linked to
<stem>.<UTC-timestamp>.sqlite first; only BACKUP_KEEP rotated generations are kept. A failure leaves the previous
file untouched, is logged, and is retried on the next tick.

Usage:
  GET /api/backup   status;   POST /api/backup   run now.
  Restore: uv run python -m backend.scripts.restore_from_sqlite --sqlite backups/sloka_mirror.sqlite [--yes]
Settings (config.py / .env): BACKUP_SQLITE_PATH, BACKUP_INTERVAL_S (0 disables), BACKUP_KEEP.
"""
import hashlib, json, logging, os, sqlite3, threading, time
from datetime import datetime, timezone
from pathlib import Path
import psycopg
from . import config as C, db

log = logging.getLogger("backup")
TABLES = ["schema_version", "verses", "meters", "voices", "jobs", "assets", "settings", "word_meanings", "verse_summaries"]
_SQLITE_TYPE = {"integer": "INTEGER", "bigint": "INTEGER", "smallint": "INTEGER", "boolean": "INTEGER",
                "real": "REAL", "double precision": "REAL", "numeric": "REAL"}

def _val(v):
    if v is None or isinstance(v, (str, int, float)) and not isinstance(v, bool): return v
    if isinstance(v, bool): return int(v)
    if isinstance(v, datetime): return v.astimezone(timezone.utc).isoformat()
    return json.dumps(v, ensure_ascii=False, sort_keys=True)       # jsonb / arrays

def _connect():
    kw = {"options": f"-c search_path={db.search_path}"} if db.search_path else {}
    return psycopg.connect(C.DATABASE_URL, autocommit=True, **kw)

def read_snapshot() -> dict:
    """{table: (columns[(name, pg_type)], rows[tuple])} from one consistent REPEATABLE READ transaction."""
    out = {}
    with _connect() as con:
        con.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
        with con.transaction():
            for t in TABLES:
                cols = con.execute("SELECT column_name, data_type FROM information_schema.columns "
                                   "WHERE table_schema=current_schema() AND table_name=%s ORDER BY ordinal_position", (t,)).fetchall()
                if not cols: raise RuntimeError(f"table {t} missing in source database")
                names = ", ".join(f'"{c}"' for c, _ in cols)
                rows = [tuple(_val(v) for v in r) for r in con.execute(f'SELECT {names} FROM "{t}"').fetchall()]
                rows.sort(key=repr)
                out[t] = (cols, rows)
    return out

def fingerprint(snap: dict) -> str:
    h = hashlib.sha256()
    for t in TABLES:
        cols, rows = snap[t]
        h.update(json.dumps([t, cols, rows], ensure_ascii=False, default=str).encode())
    return h.hexdigest()

def write_sqlite(snap: dict, path: Path, fp: str):
    path.unlink(missing_ok=True)
    con = sqlite3.connect(path)
    try:
        for t in TABLES:
            cols, rows = snap[t]
            con.execute(f'CREATE TABLE "{t}"(' + ", ".join(f'"{c}" {_SQLITE_TYPE.get(ty, "TEXT")}' for c, ty in cols) + ")")
            if rows:
                con.executemany(f'INSERT INTO "{t}" VALUES(' + ",".join("?" * len(cols)) + ")", rows)
        ver = snap["schema_version"][1]
        con.execute("CREATE TABLE _meta(key TEXT PRIMARY KEY, value TEXT)")
        con.executemany("INSERT INTO _meta VALUES(?,?)", [
            ("created_at", datetime.now(timezone.utc).isoformat()),
            ("schema_version", str(max((r[0] for r in ver), default=0))),
            ("row_counts", json.dumps({t: len(snap[t][1]) for t in TABLES})),
            ("column_types", json.dumps({t: dict(snap[t][0]) for t in TABLES})),
            ("fingerprint", fp)])
        con.commit()
        if con.execute("PRAGMA integrity_check").fetchone()[0] != "ok": raise RuntimeError("sqlite integrity_check failed")
    finally:
        con.close()
    fd = os.open(path, os.O_RDONLY)
    try: os.fsync(fd)
    finally: os.close(fd)

def read_meta(path) -> dict:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try: return dict(con.execute("SELECT key, value FROM _meta").fetchall())
    finally: con.close()

class Mirror:
    def __init__(self):
        self._lock = threading.Lock()
        self._wake = threading.Event(); self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.last_success_at = self.last_error = self.last_fingerprint = self.last_error_at = None
        self.last_run_at = None; self.rows: dict = {}

    @property
    def path(self) -> Path: return Path(C.BACKUP_SQLITE_PATH)

    def _prime(self):
        if self.last_fingerprint is None and self.path.exists():
            try:
                m = read_meta(self.path); self.last_fingerprint = m["fingerprint"]; self.rows = json.loads(m["row_counts"])
            except Exception: pass

    def _rotated(self) -> list[Path]:
        p = self.path
        return sorted(p.parent.glob(f"{p.stem}.*{p.suffix}"))

    def backup_now(self, force=False) -> dict:
        with self._lock:
            self.last_run_at = datetime.now(timezone.utc).isoformat()
            tmp = None
            try:
                self._prime()
                snap = read_snapshot(); fp = fingerprint(snap)
                self.rows = {t: len(snap[t][1]) for t in TABLES}
                if fp != self.last_fingerprint or force or not self.path.exists():
                    p = self.path; p.parent.mkdir(parents=True, exist_ok=True)
                    tmp = p.with_name(f".{p.name}.{os.getpid()}.tmp")
                    write_sqlite(snap, tmp, fp)
                    if p.exists():
                        dst = p.with_name(f"{p.stem}.{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}{p.suffix}")
                        os.link(p, dst)
                    os.replace(tmp, p); tmp = None
                    rot = self._rotated()
                    for old in rot[:max(len(rot) - max(int(C.BACKUP_KEEP), 0), 0)]: old.unlink(missing_ok=True)
                self.last_fingerprint = fp
                self.last_success_at = datetime.now(timezone.utc).isoformat(); self.last_error = None
            except Exception as e:
                self.last_error = f"{type(e).__name__}: {e}"; self.last_error_at = datetime.now(timezone.utc).isoformat()
                log.warning("backup failed: %s", self.last_error)
            finally:
                if tmp: Path(tmp).unlink(missing_ok=True)
            return self.status()

    def status(self) -> dict:
        return dict(path=str(self.path), interval_s=C.BACKUP_INTERVAL_S, keep=C.BACKUP_KEEP,
                    running=bool(self._thread and self._thread.is_alive()), last_run_at=self.last_run_at,
                    last_success_at=self.last_success_at, last_error=self.last_error, last_error_at=self.last_error_at,
                    last_fingerprint=self.last_fingerprint, rows=self.rows, generations=len(self._rotated()))

    def poke(self): self._wake.set()

    def _loop(self):
        while not self._stop.is_set():
            self.backup_now()
            self._wake.wait(max(float(C.BACKUP_INTERVAL_S), 0.05)); self._wake.clear()

    def start(self, force=False):
        if "PYTEST_CURRENT_TEST" in os.environ and not force: return     # other tests' lifespans must not write backups/
        if C.BACKUP_INTERVAL_S <= 0 or (self._thread and self._thread.is_alive()): return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="backup-mirror", daemon=True); self._thread.start()

    def stop(self):
        self._stop.set(); self._wake.set()
        if self._thread: self._thread.join(timeout=30)
        self._thread = None

_mirror: Mirror | None = None
def get() -> Mirror:
    global _mirror
    if _mirror is None: _mirror = Mirror()
    return _mirror
