"""S3 store. Credentials come from the default chain (instance role); no keys in files."""
from __future__ import annotations

import base64
import hashlib
import os
import time
from pathlib import Path
from typing import Any, Callable

from .base import Store, check_rel

DEFAULT_REGION = "ap-south-1"
_MISSING_CODES = ("404", "NoSuchKey", "NotFound")


def _error_code(exc: BaseException) -> str:
    resp = getattr(exc, "response", None)
    if isinstance(resp, dict):
        return str(resp.get("Error", {}).get("Code", ""))
    return ""


class S3Store(Store):
    def __init__(
        self,
        bucket: str,
        prefix: str = "",
        client: Any = None,
        region: str | None = None,
        attempts: int = 5,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.bucket = bucket
        self.prefix = prefix.strip("/")
        if self.prefix:
            self.prefix += "/"
        self._client = client
        self._region = region or os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or DEFAULT_REGION
        self.attempts = max(1, attempts)
        self._sleep = sleep

    @classmethod
    def from_uri(cls, uri: str, **kw: Any) -> "S3Store":
        if not uri.startswith("s3://"):
            raise ValueError(f"not an s3 uri: {uri}")
        rest = uri[len("s3://"):]
        bucket, _, prefix = rest.partition("/")
        if not bucket:
            raise ValueError(f"missing bucket in {uri}")
        return cls(bucket, prefix, **kw)

    @property
    def root(self) -> str:
        return f"s3://{self.bucket}/{self.prefix}"

    @property
    def client(self) -> Any:
        if self._client is None:
            import boto3  # lazy: tests never need it

            self._client = boto3.client("s3", region_name=self._region)
        return self._client

    def _key(self, rel: str) -> str:
        check_rel(rel)
        return self.prefix + rel

    def _retry(self, fn: Callable[[], Any]) -> Any:
        last: BaseException | None = None
        for i in range(self.attempts):
            try:
                return fn()
            except Exception as e:  # noqa: BLE001
                if isinstance(e, (ValueError, TypeError)) or _error_code(e) in _MISSING_CODES:
                    raise
                last = e
                if i < self.attempts - 1:
                    self._sleep(min(30.0, 0.5 * (2 ** i)))
        assert last is not None
        raise last

    def list(self, prefix: str) -> list[str]:
        check_rel(prefix, allow_empty=True)
        out: list[str] = []
        token: str | None = None
        while True:
            kw: dict[str, Any] = {"Bucket": self.bucket, "Prefix": self.prefix + prefix}
            if token:
                kw["ContinuationToken"] = token
            resp = self._retry(lambda kw=kw: self.client.list_objects_v2(**kw))
            for obj in resp.get("Contents", []) or []:
                out.append(obj["Key"][len(self.prefix):])
            if resp.get("IsTruncated"):
                token = resp.get("NextContinuationToken")
                if not token:
                    break
            else:
                break
        return sorted(out)

    def exists(self, rel: str) -> bool:
        key = self._key(rel)
        try:
            self._retry(lambda: self.client.head_object(Bucket=self.bucket, Key=key))
            return True
        except Exception as e:  # noqa: BLE001
            if _error_code(e) in _MISSING_CODES:
                return False
            raise

    def size(self, rel: str) -> int:
        key = self._key(rel)
        resp = self._retry(lambda: self.client.head_object(Bucket=self.bucket, Key=key))
        return int(resp["ContentLength"])

    def read(self, rel: str) -> bytes:
        key = self._key(rel)

        def go() -> bytes:
            return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()

        return self._retry(go)

    def read_range(self, rel: str, off: int, length: int) -> bytes:
        if off < 0 or length < 0:
            raise ValueError("negative range")
        if length == 0:
            return b""
        key = self._key(rel)
        rng = f"bytes={off}-{off + length - 1}"

        def go() -> bytes:
            return self.client.get_object(Bucket=self.bucket, Key=key, Range=rng)["Body"].read()

        return self._retry(go)

    def put_bytes(self, rel: str, data: bytes) -> None:
        key = self._key(rel)
        md5 = base64.b64encode(hashlib.md5(data).digest()).decode()  # noqa: S324 (integrity only)

        def go() -> None:
            self.client.put_object(Bucket=self.bucket, Key=key, Body=data, ContentMD5=md5)

        self._retry(go)

    def put_file(self, local_path: Path, rel: str) -> None:
        """Multipart upload with SHA256 checksum; verifies the stored size. Keeps the local file."""
        key = self._key(rel)
        local_path = Path(local_path)
        expect = local_path.stat().st_size

        def go() -> None:
            extra = {"ChecksumAlgorithm": "SHA256"}
            kw: dict[str, Any] = {"ExtraArgs": extra}
            try:
                from boto3.s3.transfer import TransferConfig

                mb = 1024 * 1024
                kw["Config"] = TransferConfig(multipart_threshold=64 * mb, multipart_chunksize=64 * mb)
            except Exception:  # noqa: BLE001  (fake client in tests)
                pass
            self.client.upload_file(str(local_path), self.bucket, key, **kw)
            got = int(self.client.head_object(Bucket=self.bucket, Key=key)["ContentLength"])
            if got != expect:
                raise IOError(f"upload size mismatch for {key}: {got} != {expect}")

        self._retry(go)

    def get_file(self, rel: str, local_path: Path) -> None:
        key = self._key(rel)
        local_path = Path(local_path)
        local_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = local_path.with_name(local_path.name + ".tmp-dl")

        def go() -> None:
            self.client.download_file(self.bucket, key, str(tmp))
            os.replace(tmp, local_path)

        try:
            self._retry(go)
        finally:
            if tmp.exists():
                tmp.unlink()

    def delete(self, rel: str) -> None:
        key = self._key(rel)
        self._retry(lambda: self.client.delete_object(Bucket=self.bucket, Key=key))
