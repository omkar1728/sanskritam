"""S3-protocol blob store (MinIO locally, AWS S3 or hosted MinIO in production)."""
import io
import re
import threading
from typing import Iterator, Optional

from . import config


class NotFound(KeyError):
    pass


class Unavailable(RuntimeError):
    pass


class BadRange(ValueError):
    pass


def parse_range(header: str, size: int) -> tuple[int, int]:
    """Return inclusive (start, end) for 'bytes=a-b' | 'a-' | '-n'. Raise BadRange."""
    m = re.fullmatch(r"\s*bytes\s*=\s*(\d*)\s*-\s*(\d*)\s*", header or "")
    if not m or (m.group(1) == "" and m.group(2) == ""):
        raise BadRange(header)
    a, b = m.groups()
    if a == "":
        n = int(b)
        if n == 0 or size == 0:
            raise BadRange(header)
        return max(0, size - n), size - 1
    start = int(a)
    end = size - 1 if b == "" else min(int(b), size - 1)
    if start >= size or end < start:
        raise BadRange(header)
    return start, end


def _headers(ctype: str, length: int, rng: Optional[tuple[int, int, int]]) -> dict:
    h = {"Content-Type": ctype or "application/octet-stream",
         "Content-Length": str(length), "Accept-Ranges": "bytes"}
    if rng:
        h["Content-Range"] = f"bytes {rng[0]}-{rng[1]}/{rng[2]}"
    return h


class MemoryStorage:
    def __init__(self):
        self._d: dict[str, tuple[bytes, str]] = {}

    def ensure_bucket(self):
        pass

    def put_file(self, key, path, content_type="application/octet-stream"):
        with open(path, "rb") as f:
            self._d[key] = (f.read(), content_type)

    def put_bytes(self, key, data: bytes, content_type="application/octet-stream"):
        self._d[key] = (bytes(data), content_type)

    def _get(self, key):
        try:
            return self._d[key]
        except KeyError:
            raise NotFound(key) from None

    def exists(self, key):
        return key in self._d

    def read_bytes(self, key):
        return self._get(key)[0]

    def download(self, key, path):
        with open(path, "wb") as f:
            f.write(self._get(key)[0])

    def delete(self, key):
        self._d.pop(key, None)

    def get_stream(self, key, range_header=None, chunk=65536):
        data, ctype = self._get(key)
        size = len(data)
        if range_header:
            s, e = parse_range(range_header, size)
            body, status, rng = data[s:e + 1], 206, (s, e, size)
        else:
            body, status, rng = data, 200, None
        it = (body[i:i + chunk] for i in range(0, len(body), chunk))
        return it, status, _headers(ctype, len(body), rng)


class S3Storage:
    def __init__(self):
        import boto3
        from botocore.config import Config
        self.bucket = config.S3_BUCKET
        self.client = boto3.client(
            "s3",
            endpoint_url=config.S3_ENDPOINT or None,
            aws_access_key_id=config.S3_ACCESS_KEY,
            aws_secret_access_key=config.S3_SECRET_KEY,
            region_name=config.S3_REGION,
            config=Config(
                s3={"addressing_style": "path" if config.S3_PATH_STYLE else "virtual"},
                connect_timeout=3, read_timeout=30,
                retries={"max_attempts": 2, "mode": "standard"},
            ),
        )

    def _call(self, fn, *a, key=None, **kw):
        from botocore.exceptions import BotoCoreError, ClientError
        try:
            return fn(*a, **kw)
        except ClientError as e:
            code = str(e.response.get("Error", {}).get("Code", ""))
            if code in ("404", "NoSuchKey", "NotFound", "NoSuchBucket"):
                raise NotFound(key) from e
            if code == "InvalidRange":
                raise BadRange(key) from e
            raise
        except BotoCoreError as e:  # connection / endpoint / timeout errors
            raise Unavailable(str(e)) from e

    def ensure_bucket(self):
        from botocore.exceptions import ClientError
        try:
            self._call(self.client.head_bucket, Bucket=self.bucket)
            return
        except NotFound:
            pass
        try:
            kw = {}
            if config.S3_REGION != "us-east-1":
                kw["CreateBucketConfiguration"] = {"LocationConstraint": config.S3_REGION}
            self._call(self.client.create_bucket, Bucket=self.bucket, **kw)
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") not in (
                    "BucketAlreadyOwnedByYou", "BucketAlreadyExists"):
                raise

    def put_file(self, key, path, content_type="application/octet-stream"):
        self._call(self.client.upload_file, str(path), self.bucket, key,
                   ExtraArgs={"ContentType": content_type})

    def put_bytes(self, key, data: bytes, content_type="application/octet-stream"):
        self._call(self.client.put_object, Bucket=self.bucket, Key=key,
                   Body=data, ContentType=content_type)

    def exists(self, key):
        try:
            self._call(self.client.head_object, Bucket=self.bucket, Key=key, key=key)
            return True
        except NotFound:
            return False

    def download(self, key, path):
        self._call(self.client.download_file, self.bucket, key, str(path), key=key)

    def read_bytes(self, key):
        r = self._call(self.client.get_object, Bucket=self.bucket, Key=key, key=key)
        return r["Body"].read()

    def delete(self, key):
        self._call(self.client.delete_object, Bucket=self.bucket, Key=key)

    def get_stream(self, key, range_header=None, chunk=65536):
        kw = {}
        if range_header:
            if not re.fullmatch(r"\s*bytes\s*=\s*(\d+-\d*|-\d+)\s*", range_header):
                raise BadRange(range_header)
            kw["Range"] = range_header.strip()
        r = self._call(self.client.get_object, Bucket=self.bucket, Key=key, key=key, **kw)
        status = 206 if range_header else 200
        rng = None
        if status == 206:
            m = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", r.get("ContentRange", ""))
            if m:
                rng = tuple(int(x) for x in m.groups())
        h = _headers(r.get("ContentType"), r["ContentLength"], rng)
        body = r["Body"]

        def it() -> Iterator[bytes]:
            try:
                yield from body.iter_chunks(chunk)
            finally:
                body.close()
        return it(), status, h


_backend = None
_lock = threading.Lock()


def get():
    global _backend
    with _lock:
        if _backend is None:
            kind = config.STORAGE_BACKEND
            if kind == "memory":
                _backend = MemoryStorage()
            elif kind == "s3":
                _backend = S3Storage()
            else:
                raise ValueError(f"unknown STORAGE_BACKEND {kind!r}")
        return _backend


def set_backend(obj):
    global _backend
    with _lock:
        _backend = obj
