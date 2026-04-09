"""ObjectStore protocol and concrete implementations (local filesystem + S3)."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class ObjectStore(Protocol):
    def read(self, path: str) -> bytes: ...
    def write(self, path: str, data: bytes) -> None: ...
    def list(self, prefix: str) -> list[str]: ...
    def delete(self, path: str) -> None: ...


class LocalStore:
    """ObjectStore backed by the local filesystem."""

    def read(self, path: str) -> bytes:
        try:
            return Path(path).read_bytes()
        except FileNotFoundError as exc:
            raise FileNotFoundError(path) from exc

    def write(self, path: str, data: bytes) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    def list(self, prefix: str) -> list[str]:
        root = Path(prefix)
        if not root.exists():
            return []
        return sorted(
            str(p) for p in root.rglob("*.parquet") if p.is_file()
        )

    def delete(self, path: str) -> None:
        Path(path).unlink()


class S3Store:
    """ObjectStore backed by Amazon S3 using boto3."""

    def __init__(self, bucket: str, prefix: str = "") -> None:
        try:
            import boto3  # type: ignore
        except ImportError as exc:
            raise ImportError(
                "boto3 is required for S3 storage. "
                "Install it with: pip install agentic-adoption-scan[s3]"
            ) from exc
        self._bucket = bucket
        self._prefix = prefix
        self._client = boto3.client("s3")

    def _full_key(self, path: str) -> str:
        if self._prefix:
            return f"{self._prefix.rstrip('/')}/{path.lstrip('/')}"
        return path

    def read(self, path: str) -> bytes:
        import botocore.exceptions  # type: ignore

        key = self._full_key(path)
        try:
            resp = self._client.get_object(Bucket=self._bucket, Key=key)
            return resp["Body"].read()
        except botocore.exceptions.ClientError as exc:
            code = exc.response["Error"]["Code"]
            if code in ("NoSuchKey", "404"):
                raise FileNotFoundError(f"s3://{self._bucket}/{key}") from exc
            raise

    def write(self, path: str, data: bytes) -> None:
        key = self._full_key(path)
        self._client.put_object(Bucket=self._bucket, Key=key, Body=data)

    def list(self, prefix: str) -> list[str]:
        full_prefix = self._full_key(prefix)
        keys: list[str] = []
        paginator = self._client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self._bucket, Prefix=full_prefix):
            for obj in page.get("Contents", []):
                k = obj["Key"]
                if k.endswith(".parquet"):
                    keys.append(k)
        return keys

    def delete(self, path: str) -> None:
        key = self._full_key(path)
        self._client.delete_object(Bucket=self._bucket, Key=key)


def parse_store_path(raw: str) -> tuple[ObjectStore, str]:
    """Return (store, base_path) for *raw*.

    s3://bucket/key  -> (S3Store(bucket), key)
    /local/path      -> (LocalStore(), /local/path)
    """
    if raw.startswith("s3://"):
        rest = raw[len("s3://"):]
        parts = rest.split("/", 1)
        bucket = parts[0]
        key = parts[1] if len(parts) > 1 else ""
        return S3Store(bucket), key
    return LocalStore(), raw
