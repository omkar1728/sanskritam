"""Store tests: LocalStore on tmp_path, S3Store against a fake in-memory client (no network)."""
from __future__ import annotations

import io
from pathlib import Path

import pytest

from pipeline.stores import LocalStore, S3Store, default_dest, open_store
from pipeline.stores.base import Store


def test_local_roundtrip(tmp_path):
    s = LocalStore(tmp_path / "st")
    assert s.list("") == []
    s.put_bytes("a/b.txt", b"hello world")
    assert s.exists("a/b.txt") and not s.exists("a/c.txt")
    assert s.read("a/b.txt") == b"hello world"
    assert s.read_range("a/b.txt", 6, 5) == b"world"
    assert s.size("a/b.txt") == 11
    assert s.list("a/") == ["a/b.txt"]
    assert s.list("a/b") == ["a/b.txt"]
    assert s.list("zzz/") == []
    s.delete("a/b.txt")
    s.delete("a/b.txt")  # idempotent
    assert not s.exists("a/b.txt")


def test_local_put_file_keeps_local_and_get_file(tmp_path):
    s = LocalStore(tmp_path / "st")
    src = tmp_path / "src.bin"
    src.write_bytes(b"xyz")
    s.put_file(src, "p/q.bin")
    assert src.exists() and s.read("p/q.bin") == b"xyz"
    out = tmp_path / "out" / "q.bin"
    s.get_file("p/q.bin", out)
    assert out.read_bytes() == b"xyz"
    assert not [k for k in s.list("") if ".tmp-" in k]
    import hashlib

    assert s.sha256("p/q.bin") == hashlib.sha256(b"xyz").hexdigest()


@pytest.mark.parametrize("bad", ["../x", "a/../../x", "/abs", "a\\b", ""])
def test_local_rejects_bad_keys(tmp_path, bad):
    s = LocalStore(tmp_path / "st")
    with pytest.raises(ValueError):
        s.put_bytes(bad, b"x")
    with pytest.raises(ValueError):
        s.read(bad)


def test_local_list_rejects_dotdot(tmp_path):
    with pytest.raises(ValueError):
        LocalStore(tmp_path).list("../")


def test_open_store_variants(tmp_path):
    assert isinstance(open_store(str(tmp_path)), LocalStore)
    g = open_store("gdrive:")
    assert g.root.rstrip("/").endswith("/content/drive/MyDrive/sloka_pipeline")
    g2 = open_store("gdrive:ramayana")
    assert g2.root.endswith("sloka_pipeline/ramayana")
    s3 = open_store("s3://bucket/some/prefix")
    assert isinstance(s3, S3Store) and s3.root == "s3://bucket/some/prefix/"


def test_default_dest():
    assert default_dest("aws", "ramayana") == "s3://sloka-poc-audio-785703562757/pipeline/ramayana/"
    assert default_dest("colab", "ramayana") == "/content/drive/MyDrive/sloka_pipeline/ramayana/"
    d = default_dest("local", "ramayana")
    assert d.endswith("/pipeline/output/ramayana/")


# ---- fake S3 client
class NotFound(Exception):
    def __init__(self):
        self.response = {"Error": {"Code": "404"}}


class FakeS3:
    def __init__(self):
        self.objs: dict[str, bytes] = {}
        self.upload_failures = 0
        self.uploads = 0

    def put_object(self, Bucket, Key, Body, ContentMD5=None):
        assert ContentMD5
        self.objs[Key] = bytes(Body)

    def upload_file(self, Filename, Bucket, Key, ExtraArgs=None, Config=None):
        self.uploads += 1
        if self.upload_failures:
            self.upload_failures -= 1
            raise ConnectionError("flaky")
        assert ExtraArgs and ExtraArgs.get("ChecksumAlgorithm") == "SHA256"
        self.objs[Key] = Path(Filename).read_bytes()

    def download_file(self, Bucket, Key, Filename):
        Path(Filename).write_bytes(self.objs[Key])

    def head_object(self, Bucket, Key):
        if Key not in self.objs:
            raise NotFound()
        return {"ContentLength": len(self.objs[Key])}

    def get_object(self, Bucket, Key, Range=None):
        if Key not in self.objs:
            raise NotFound()
        data = self.objs[Key]
        if Range:
            a, b = Range[len("bytes="):].split("-")
            data = data[int(a): int(b) + 1]
        return {"Body": io.BytesIO(data)}

    def list_objects_v2(self, Bucket, Prefix, ContinuationToken=None):
        keys = sorted(k for k in self.objs if k.startswith(Prefix))
        start = int(ContinuationToken) if ContinuationToken else 0
        page = keys[start:start + 2]  # tiny pages to exercise pagination
        resp = {"Contents": [{"Key": k} for k in page]}
        if start + 2 < len(keys):
            resp["IsTruncated"] = True
            resp["NextContinuationToken"] = str(start + 2)
        return resp

    def delete_object(self, Bucket, Key):
        self.objs.pop(Key, None)


def test_s3_store_with_fake_client(tmp_path):
    fake = FakeS3()
    s = S3Store("bkt", "pipe/ramayana", client=fake, sleep=lambda _s: None)
    s.put_bytes("segments/a.idx.jsonl", b"1")
    s.put_bytes("segments/b.idx.jsonl", b"22")
    s.put_bytes("segments/c.idx.jsonl", b"333")
    s.put_bytes("manifest.json", b"{}")
    assert "pipe/ramayana/manifest.json" in fake.objs
    assert s.list("segments/") == ["segments/a.idx.jsonl", "segments/b.idx.jsonl", "segments/c.idx.jsonl"]
    assert s.exists("manifest.json") and not s.exists("nope")
    assert s.size("segments/c.idx.jsonl") == 3
    assert s.read_range("segments/c.idx.jsonl", 1, 2) == b"33"
    f = tmp_path / "up.bin"
    f.write_bytes(b"payload")
    fake.upload_failures = 2
    s.put_file(f, "segments/d.audio.pack")
    assert fake.uploads == 3 and f.exists()  # retried, local kept
    out = tmp_path / "dl.bin"
    s.get_file("segments/d.audio.pack", out)
    assert out.read_bytes() == b"payload"
    s.delete("segments/d.audio.pack")
    assert not s.exists("segments/d.audio.pack")
    with pytest.raises(ValueError):
        s.read("../x")


def test_s3_gives_up_after_attempts(tmp_path):
    fake = FakeS3()
    fake.upload_failures = 99
    s = S3Store("bkt", "p", client=fake, attempts=3, sleep=lambda _s: None)
    f = tmp_path / "x"
    f.write_bytes(b"1")
    with pytest.raises(ConnectionError):
        s.put_file(f, "k")
    assert fake.uploads == 3 and f.exists()


class MemStore(Store):
    """Minimal in-memory Store used to check the base-class helpers."""

    def __init__(self):
        self.d: dict[str, bytes] = {}

    root = "mem://"

    def list(self, prefix): return sorted(k for k in self.d if k.startswith(prefix))
    def exists(self, rel): return rel in self.d
    def read(self, rel): return self.d[rel]
    def read_range(self, rel, off, length): return self.d[rel][off:off + length]
    def put_file(self, local_path, rel): self.d[rel] = Path(local_path).read_bytes()
    def put_bytes(self, rel, data): self.d[rel] = data
    def get_file(self, rel, local_path): Path(local_path).write_bytes(self.d[rel])
    def delete(self, rel): self.d.pop(rel, None)


def test_base_size_and_sha_defaults():
    import hashlib

    m = MemStore()
    m.put_bytes("a", b"abcdef" * 10)
    assert m.size("a") == 60
    assert m.sha256("a", chunk=7) == hashlib.sha256(b"abcdef" * 10).hexdigest()


def test_default_dest_kaggle():
    assert default_dest("kaggle", "ramayana") == default_dest("aws", "ramayana")
