"""Durable/private object storage with a filesystem fallback for local development."""

from __future__ import annotations

import asyncio
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import AsyncIterator, Optional


LOCAL_STORAGE_BACKEND = "local"
VERCEL_BLOB_STORAGE_BACKEND = "vercel_blob"
SUPPORTED_STORAGE_BACKENDS = {
    LOCAL_STORAGE_BACKEND,
    VERCEL_BLOB_STORAGE_BACKEND,
}


def configured_object_storage_backend() -> str:
    """Choose Blob on Vercel and local files for ordinary local development."""
    configured = os.getenv("OBJECT_STORAGE_BACKEND", "").strip().lower()
    if configured:
        if configured not in SUPPORTED_STORAGE_BACKENDS:
            raise RuntimeError(
                "OBJECT_STORAGE_BACKEND must be either 'local' or 'vercel_blob'"
            )
        return configured
    if os.getenv("VERCEL") or os.getenv("BLOB_READ_WRITE_TOKEN"):
        return VERCEL_BLOB_STORAGE_BACKEND
    return LOCAL_STORAGE_BACKEND


@dataclass(frozen=True)
class StoredObjectReference:
    backend: str
    key: str
    url: Optional[str] = None


@dataclass
class StoredObjectDownload:
    backend: str
    key: str
    content_type: str
    local_path: Optional[Path] = None
    stream: Optional[AsyncIterator[bytes]] = None
    etag: Optional[str] = None
    size: Optional[int] = None


@dataclass(frozen=True)
class MaterializedStoredObject:
    download: StoredObjectDownload
    path: Path
    temporary: bool


class ObjectStorage:
    """Store one controlled key namespace in local files or private Vercel Blob."""

    def __init__(
        self,
        *,
        local_root: Path,
        key_prefix: PurePosixPath,
        backend: Optional[str] = None,
    ) -> None:
        self.local_root = local_root.resolve()
        self.key_prefix = key_prefix
        self.backend = backend or configured_object_storage_backend()
        if self.backend not in SUPPORTED_STORAGE_BACKENDS:
            raise RuntimeError(f"Unsupported object storage backend: {self.backend}")
        if (
            self.backend == VERCEL_BLOB_STORAGE_BACKEND
            and not os.getenv("BLOB_READ_WRITE_TOKEN", "").strip()
        ):
            raise RuntimeError(
                "BLOB_READ_WRITE_TOKEN is required when object storage uses Vercel Blob"
            )

    def _validated_key(self, key: str) -> PurePosixPath:
        try:
            key_path = PurePosixPath(key)
        except (TypeError, ValueError) as exc:
            raise ValueError("Invalid object storage key") from exc

        prefix_parts = self.key_prefix.parts
        if (
            key_path.is_absolute()
            or ".." in key_path.parts
            or key_path.parts[: len(prefix_parts)] != prefix_parts
            or len(key_path.parts) <= len(prefix_parts)
        ):
            raise ValueError("Object storage key is outside the configured namespace")
        return key_path

    def _local_path(self, key: str) -> Path:
        key_path = self._validated_key(key)
        relative_parts = key_path.parts[len(self.key_prefix.parts) :]
        resolved = self.local_root.joinpath(*relative_parts).resolve()
        if self.local_root != resolved and self.local_root not in resolved.parents:
            raise ValueError("Object storage key resolves outside the local storage root")
        return resolved

    async def put_bytes(
        self,
        key: str,
        contents: bytes,
        *,
        content_type: str,
    ) -> StoredObjectReference:
        self._validated_key(key)
        if self.backend == LOCAL_STORAGE_BACKEND:
            path = self._local_path(key)

            def write_atomically() -> None:
                path.parent.mkdir(parents=True, exist_ok=True)
                temporary_path: Optional[Path] = None
                try:
                    with tempfile.NamedTemporaryFile(
                        dir=path.parent,
                        prefix=f".{path.name}.",
                        suffix=".tmp",
                        delete=False,
                    ) as temporary:
                        temporary_path = Path(temporary.name)
                        temporary.write(contents)
                    temporary_path.replace(path)
                except Exception:
                    if temporary_path:
                        temporary_path.unlink(missing_ok=True)
                    raise

            await asyncio.to_thread(write_atomically)
            return StoredObjectReference(backend=self.backend, key=key)

        from vercel.blob import AsyncBlobClient

        async with AsyncBlobClient() as client:
            uploaded = await client.put(
                key,
                contents,
                access="private",
                content_type=content_type,
                add_random_suffix=False,
                overwrite=False,
            )
        return StoredObjectReference(
            backend=self.backend,
            key=uploaded.pathname,
            url=uploaded.url,
        )

    async def delete(self, key: str, *, backend: Optional[str] = None) -> None:
        selected_backend = backend or self.backend
        self._validated_key(key)
        if selected_backend == LOCAL_STORAGE_BACKEND:
            path = self._local_path(key)
            await asyncio.to_thread(path.unlink, missing_ok=True)
            return
        if selected_backend != VERCEL_BLOB_STORAGE_BACKEND:
            raise ValueError(f"Unsupported object storage backend: {selected_backend}")

        from vercel.blob import AsyncBlobClient

        async with AsyncBlobClient() as client:
            await client.delete(key)

    async def exists(self, key: str, *, backend: Optional[str] = None) -> bool:
        selected_backend = backend or self.backend
        self._validated_key(key)
        if selected_backend == LOCAL_STORAGE_BACKEND:
            return await asyncio.to_thread(self._local_path(key).is_file)
        if selected_backend != VERCEL_BLOB_STORAGE_BACKEND:
            return False

        from vercel.blob import AsyncBlobClient
        from vercel.blob.errors import BlobNotFoundError

        try:
            async with AsyncBlobClient() as client:
                await client.head(key)
            return True
        except BlobNotFoundError:
            return False

    async def get(
        self,
        key: str,
        *,
        backend: Optional[str] = None,
        default_content_type: str = "application/octet-stream",
    ) -> Optional[StoredObjectDownload]:
        selected_backend = backend or self.backend
        self._validated_key(key)
        if selected_backend == LOCAL_STORAGE_BACKEND:
            path = self._local_path(key)
            if not await asyncio.to_thread(path.is_file):
                return None
            return StoredObjectDownload(
                backend=selected_backend,
                key=key,
                content_type=default_content_type,
                local_path=path,
                size=path.stat().st_size,
            )
        if selected_backend != VERCEL_BLOB_STORAGE_BACKEND:
            return None

        from vercel.blob import AsyncBlobClient

        client = AsyncBlobClient()
        try:
            result = await client.get(key, access="private")
            if result is None or result.status_code != 200 or result.stream is None:
                await client.aclose()
                return None
        except Exception:
            await client.aclose()
            raise

        async def stream_with_cleanup() -> AsyncIterator[bytes]:
            try:
                async for chunk in result.stream:
                    yield chunk
            finally:
                await client.aclose()

        return StoredObjectDownload(
            backend=selected_backend,
            key=key,
            content_type=result.blob.content_type or default_content_type,
            stream=stream_with_cleanup(),
            etag=result.blob.etag,
            size=result.blob.size,
        )

    async def materialize(
        self,
        key: str,
        *,
        backend: Optional[str] = None,
        suffix: str = "",
        default_content_type: str = "application/octet-stream",
    ) -> Optional[MaterializedStoredObject]:
        """Return a local path for processing without assuming durable storage is local."""
        download = await self.get(
            key,
            backend=backend,
            default_content_type=default_content_type,
        )
        if download is None:
            return None
        if download.local_path is not None:
            return MaterializedStoredObject(
                download=download,
                path=download.local_path,
                temporary=False,
            )
        if download.stream is None:
            return None

        temporary_path: Optional[Path] = None
        bytes_written = 0
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temporary:
                temporary_path = Path(temporary.name)
                async for chunk in download.stream:
                    temporary.write(chunk)
                    bytes_written += len(chunk)
            if download.size is not None and bytes_written != download.size:
                raise IOError("Stored object download size did not match its metadata")
            return MaterializedStoredObject(
                download=download,
                path=temporary_path,
                temporary=True,
            )
        except Exception:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            raise
