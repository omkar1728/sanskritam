import sys, uuid
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))


@pytest.fixture(scope="session")
def pg_url():
    import psycopg
    from backend.app import config as C
    try:
        psycopg.connect(C.TEST_DATABASE_URL, connect_timeout=3).close()
    except Exception as e:
        pytest.skip(f"Postgres not reachable at TEST_DATABASE_URL ({C.TEST_DATABASE_URL}): {e}. "
                    "Start it with `docker compose up -d` (or see backend/tests/conftest.py).", allow_module_level=False)
    return C.TEST_DATABASE_URL


@pytest.fixture()
def pg(pg_url, monkeypatch):
    """Fresh throwaway schema per test; DATABASE_URL points at the test database."""
    import psycopg
    from backend.app import config as C, db
    schema = "t_" + uuid.uuid4().hex[:10]
    with psycopg.connect(pg_url, autocommit=True) as admin:
        admin.execute(f"CREATE SCHEMA {schema}")
    monkeypatch.setattr(C, "DATABASE_URL", pg_url)
    monkeypatch.setattr(db, "search_path", schema)
    db.reset_connection()
    yield schema
    db.reset_connection()
    with psycopg.connect(pg_url, autocommit=True) as admin:
        admin.execute(f"DROP SCHEMA {schema} CASCADE")


@pytest.fixture()
def mem_storage():
    from backend.app import storage
    st = storage.MemoryStorage()
    storage.set_backend(st)
    yield st
    storage.set_backend(None)
