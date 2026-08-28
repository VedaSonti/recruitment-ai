import asyncio
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path, PurePosixPath
from unittest.mock import patch

from object_storage import (
    LOCAL_STORAGE_BACKEND,
    VERCEL_BLOB_STORAGE_BACKEND,
    ObjectStorage,
    configured_object_storage_backend,
)


class ObjectStorageTests(unittest.TestCase):
    def _fake_blob_modules(self, client_class):
        vercel_module = types.ModuleType("vercel")
        blob_module = types.ModuleType("vercel.blob")
        errors_module = types.ModuleType("vercel.blob.errors")
        blob_module.AsyncBlobClient = client_class
        errors_module.BlobNotFoundError = type("BlobNotFoundError", (Exception,), {})
        vercel_module.blob = blob_module
        return {
            "vercel": vercel_module,
            "vercel.blob": blob_module,
            "vercel.blob.errors": errors_module,
        }

    def test_local_storage_round_trip_and_delete(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = ObjectStorage(
                local_root=Path(directory),
                key_prefix=PurePosixPath("media/candidates"),
                backend=LOCAL_STORAGE_BACKEND,
            )
            key = "media/candidates/candidate-1/original.pdf"

            reference = asyncio.run(
                storage.put_bytes(key, b"original", content_type="application/pdf")
            )
            download = asyncio.run(
                storage.get(key, default_content_type="application/pdf")
            )

            self.assertEqual(reference.backend, LOCAL_STORAGE_BACKEND)
            self.assertEqual(reference.key, key)
            self.assertIsNotNone(download)
            self.assertEqual(download.local_path.read_bytes(), b"original")
            self.assertTrue(asyncio.run(storage.exists(key)))

            asyncio.run(storage.delete(key))
            self.assertFalse(asyncio.run(storage.exists(key)))

    def test_storage_key_cannot_escape_namespace(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = ObjectStorage(
                local_root=Path(directory),
                key_prefix=PurePosixPath("media/candidates"),
                backend=LOCAL_STORAGE_BACKEND,
            )
            with self.assertRaises(ValueError):
                asyncio.run(
                    storage.put_bytes(
                        "media/candidates/../outside.pdf",
                        b"unsafe",
                        content_type="application/pdf",
                    )
                )

    def test_local_is_default_outside_vercel(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(configured_object_storage_backend(), LOCAL_STORAGE_BACKEND)

    def test_vercel_requires_blob_token(self):
        with patch.dict(os.environ, {"VERCEL": "1"}, clear=True):
            self.assertEqual(
                configured_object_storage_backend(),
                VERCEL_BLOB_STORAGE_BACKEND,
            )
            with tempfile.TemporaryDirectory() as directory:
                with self.assertRaisesRegex(RuntimeError, "BLOB_READ_WRITE_TOKEN"):
                    ObjectStorage(
                        local_root=Path(directory),
                        key_prefix=PurePosixPath("media/candidates"),
                    )

    def test_explicit_local_override_preserves_local_vercel_development(self):
        with patch.dict(
            os.environ,
            {"VERCEL": "1", "OBJECT_STORAGE_BACKEND": "local"},
            clear=True,
        ):
            self.assertEqual(configured_object_storage_backend(), LOCAL_STORAGE_BACKEND)

    def test_private_blob_upload_uses_sdk_and_closes_client(self):
        events = []

        class FakeClient:
            async def __aenter__(self):
                events.append("enter")
                return self

            async def __aexit__(self, *_args):
                events.append("exit")

            async def put(self, key, contents, **options):
                events.append(("put", key, contents, options))
                return types.SimpleNamespace(pathname=key, url=f"https://private/{key}")

        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ,
            {"BLOB_READ_WRITE_TOKEN": "test-token"},
            clear=True,
        ), patch.dict(sys.modules, self._fake_blob_modules(FakeClient)):
            storage = ObjectStorage(
                local_root=Path(directory),
                key_prefix=PurePosixPath("media/candidates"),
                backend=VERCEL_BLOB_STORAGE_BACKEND,
            )
            key = "media/candidates/candidate-1/original.pdf"
            reference = asyncio.run(
                storage.put_bytes(key, b"original", content_type="application/pdf")
            )

        self.assertEqual(reference.key, key)
        self.assertEqual(events[0], "enter")
        self.assertEqual(events[-1], "exit")
        self.assertEqual(events[1][0:3], ("put", key, b"original"))
        self.assertEqual(events[1][3]["access"], "private")
        self.assertFalse(events[1][3]["overwrite"])

    def test_private_blob_download_closes_client_after_streaming(self):
        events = []

        async def blob_stream():
            yield b"part-1"
            yield b"part-2"

        class FakeClient:
            async def get(self, key, **options):
                events.append(("get", key, options))
                blob = types.SimpleNamespace(
                    content_type="application/pdf",
                    etag="etag-1",
                    size=12,
                )
                return types.SimpleNamespace(status_code=200, stream=blob_stream(), blob=blob)

            async def aclose(self):
                events.append("close")

        async def download_all(storage, key):
            download = await storage.get(key, backend=VERCEL_BLOB_STORAGE_BACKEND)
            chunks = []
            async for chunk in download.stream:
                chunks.append(chunk)
            return download, b"".join(chunks)

        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ,
            {"BLOB_READ_WRITE_TOKEN": "test-token"},
            clear=True,
        ), patch.dict(sys.modules, self._fake_blob_modules(FakeClient)):
            storage = ObjectStorage(
                local_root=Path(directory),
                key_prefix=PurePosixPath("media/candidates"),
                backend=VERCEL_BLOB_STORAGE_BACKEND,
            )
            key = "media/candidates/candidate-1/original.pdf"
            download, contents = asyncio.run(download_all(storage, key))

        self.assertEqual(contents, b"part-1part-2")
        self.assertEqual(download.content_type, "application/pdf")
        self.assertEqual(events[0], ("get", key, {"access": "private"}))
        self.assertEqual(events[-1], "close")

    def test_private_blob_materializes_to_a_temporary_file_and_closes_client(self):
        events = []

        async def blob_stream():
            yield b"video-"
            yield b"bytes"

        class FakeClient:
            async def get(self, key, **options):
                events.append(("get", key, options))
                blob = types.SimpleNamespace(
                    content_type="video/webm",
                    etag="etag-video",
                    size=11,
                )
                return types.SimpleNamespace(status_code=200, stream=blob_stream(), blob=blob)

            async def aclose(self):
                events.append("close")

        async def materialize(storage, key):
            result = await storage.materialize(
                key,
                backend=VERCEL_BLOB_STORAGE_BACKEND,
                suffix=".webm",
                default_content_type="video/webm",
            )
            contents = result.path.read_bytes()
            result.path.unlink()
            return result, contents

        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ,
            {"BLOB_READ_WRITE_TOKEN": "test-token"},
            clear=True,
        ), patch.dict(sys.modules, self._fake_blob_modules(FakeClient)):
            storage = ObjectStorage(
                local_root=Path(directory),
                key_prefix=PurePosixPath("media/interviews"),
                backend=VERCEL_BLOB_STORAGE_BACKEND,
            )
            key = "media/interviews/interview-1/0.webm"
            materialized, contents = asyncio.run(materialize(storage, key))

        self.assertTrue(materialized.temporary)
        self.assertEqual(contents, b"video-bytes")
        self.assertEqual(events[-1], "close")


if __name__ == "__main__":
    unittest.main()
