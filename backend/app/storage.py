"""Content-addressed blob storage, outside the web root.

Blobs are keyed by sha256. Dedup is a storage detail only: access is always granted through
workspace-scoped EvidenceFile rows, never by blob hash, so identical files uploaded in two
workspaces do not leak across them.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Protocol

from .config import get_settings


class BlobStore(Protocol):
    def put(self, data: bytes) -> str: ...
    def get(self, key: str) -> bytes: ...
    def path(self, key: str) -> Path: ...


class LocalBlobStore:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, key: str) -> Path:
        if len(key) != 64 or not all(c in "0123456789abcdef" for c in key):
            raise ValueError("bad blob key")
        return self.root / key[:2] / key

    def put(self, data: bytes) -> str:
        key = hashlib.sha256(data).hexdigest()
        p = self.path(key)
        if not p.exists():
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".tmp")
            tmp.write_bytes(data)
            tmp.replace(p)
        return key

    def get(self, key: str) -> bytes:
        return self.path(key).read_bytes()


_store: BlobStore | None = None


def get_store() -> BlobStore:
    global _store
    if _store is None:
        _store = LocalBlobStore(get_settings().blob_dir)
    return _store


def set_store(store: BlobStore | None) -> None:
    global _store
    _store = store
