"""Local filesystem storage backend. Designed to be swappable for S3 later.

All artifact paths in the DB are stored as relative POSIX strings under the storage root.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Protocol

from app.config import settings


class StorageBackend(ABC):
    @abstractmethod
    def absolute(self, rel: str) -> Path: ...

    @abstractmethod
    def job_dir(self, job_id: int) -> Path: ...

    @abstractmethod
    def write_bytes(self, rel: str, data: bytes) -> str: ...

    @abstractmethod
    def url(self, rel: str) -> str: ...


class LocalStorage(StorageBackend):
    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or settings.storage_root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def absolute(self, rel: str) -> Path:
        return self.root / rel

    def job_dir(self, job_id: int) -> Path:
        d = self.root / f"job_{job_id}"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def write_bytes(self, rel: str, data: bytes) -> str:
        p = self.absolute(rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return rel

    def url(self, rel: str) -> str:
        # Served by FastAPI StaticFiles mounted at /files
        return f"/files/{rel.replace(chr(92), '/')}"


storage: StorageBackend = LocalStorage()
