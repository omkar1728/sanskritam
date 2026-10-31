import socket
import urllib.parse
import uuid

import pytest

from backend.app import config, storage
from backend.app.storage import BadRange, MemoryStorage, NotFound, S3Storage

DATA = bytes(range(256)) * 4  # 1024 bytes


def _drain(it):
    return b"".join(it)


def _contract(st, tmp_path):
    f = tmp_path / "a.bin"
    f.write_bytes(DATA)
    st.put_file("x/a.bin", f, "audio/mpeg")
    assert st.exists("x/a.bin") and not st.exists("x/nope")
    assert st.read_bytes("x/a.bin") == DATA
    out = tmp_path / "o.bin"
    st.download("x/a.bin", out)
    assert out.read_bytes() == DATA

    it, status, h = st.get_stream("x/a.bin")
    assert status == 200 and _drain(it) == DATA
    assert h["Content-Type"] == "audio/mpeg" and h["Content-Length"] == "1024"
    assert h["Accept-Ranges"] == "bytes" and "Content-Range" not in h

    it, status, h = st.get_stream("x/a.bin", "bytes=10-19")
    assert status == 206 and _drain(it) == DATA[10:20]
    assert h["Content-Range"] == "bytes 10-19/1024" and h["Content-Length"] == "10"
    it, status, h = st.get_stream("x/a.bin", "bytes=1000-")
    assert _drain(it) == DATA[1000:] and h["Content-Range"] == "bytes 1000-1023/1024"
    it, status, h = st.get_stream("x/a.bin", "bytes=-5")
    assert _drain(it) == DATA[-5:] and h["Content-Range"] == "bytes 1019-1023/1024"
    it, _, h = st.get_stream("x/a.bin", "bytes=1000-5000")
    assert _drain(it) == DATA[1000:]

    for bad in ("bytes=2000-", "bytes=abc", "bytes=5-2", "items=0-1", "bytes=-0"):
        with pytest.raises(BadRange):
            st.get_stream("x/a.bin", bad)

    with pytest.raises(NotFound):
        st.get_stream("x/nope")
    with pytest.raises(NotFound):
        st.read_bytes("x/nope")
    with pytest.raises(KeyError):
        st.download("x/nope", tmp_path / "z")
    st.delete("x/a.bin")
    st.delete("x/a.bin")  # idempotent
    assert not st.exists("x/a.bin")


def test_memory_contract(tmp_path):
    st = MemoryStorage()
    st.ensure_bucket()
    _contract(st, tmp_path)


def test_singleton_and_set_backend():
    old = storage._backend
    try:
        m = MemoryStorage()
        storage.set_backend(m)
        assert storage.get() is m
    finally:
        storage.set_backend(old)


def _minio_up():
    if not config.S3_ENDPOINT:
        return False
    u = urllib.parse.urlparse(config.S3_ENDPOINT)
    try:
        socket.create_connection((u.hostname, u.port or (443 if u.scheme == "https" else 80)), 1.5).close()
        return True
    except OSError:
        return False


@pytest.fixture
def s3(monkeypatch):
    if not _minio_up():
        pytest.skip(f"MinIO/S3 not reachable at S3_ENDPOINT={config.S3_ENDPOINT!r} "
                    "(run: docker compose up -d minio)")
    monkeypatch.setattr(config, "S3_BUCKET", "test-" + uuid.uuid4().hex[:12])
    st = S3Storage()
    st.ensure_bucket()
    yield st
    try:
        for o in st.client.list_objects_v2(Bucket=st.bucket).get("Contents", []):
            st.client.delete_object(Bucket=st.bucket, Key=o["Key"])
        st.client.delete_bucket(Bucket=st.bucket)
    except Exception:
        pass


def test_s3_contract(s3, tmp_path):
    s3.ensure_bucket()  # idempotent
    _contract(s3, tmp_path)


def test_s3_unavailable(monkeypatch):
    monkeypatch.setattr(config, "S3_ENDPOINT", "http://127.0.0.1:1")
    st = S3Storage()
    with pytest.raises(storage.Unavailable):
        st.exists("k")
