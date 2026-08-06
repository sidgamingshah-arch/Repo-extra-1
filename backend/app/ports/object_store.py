"""Object-store port + a local-filesystem implementation.

Files are never stored in the database — only object keys + sha256 hashes. The
local implementation keeps the app runnable with zero external services; S3/MinIO
implementations plug in behind the same interface.
"""
from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class ObjectStore(Protocol):
    id: str

    def put(self, key: str, data: bytes) -> str: ...
    def get(self, key: str) -> bytes: ...
    def exists(self, key: str) -> bool: ...
    def delete(self, key: str) -> None: ...


class LocalObjectStore:
    """Stores objects under a content-addressed path on the local filesystem."""

    id = "local"

    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        # Shard by first 2 hex chars when the key looks like a hash, else flat.
        safe = key.replace("/", "_")
        return self.root / safe

    def put(self, key: str, data: bytes) -> str:
        p = self._path(key)
        p.write_bytes(data)
        return key

    def put_bytes(self, data: bytes) -> str:
        """Content-addressed put — returns the sha256 key."""
        key = hashlib.sha256(data).hexdigest()
        self.put(key, data)
        return key

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def exists(self, key: str) -> bool:
        return self._path(key).exists()

    def delete(self, key: str) -> None:
        p = self._path(key)
        if p.exists():
            p.unlink()

    def clear(self) -> None:  # test helper
        if self.root.exists():
            shutil.rmtree(self.root)
        self.root.mkdir(parents=True, exist_ok=True)
