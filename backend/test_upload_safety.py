import ast
import asyncio
import hashlib
import unittest
from pathlib import Path
import tempfile
from typing import Optional


class FakeHTTPException(Exception):
    def __init__(self, status_code, detail):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class FakeObjectId:
    next_value = 0

    def __new__(cls):
        cls.next_value += 1
        return f"candidate-{cls.next_value}"


class FakeParent:
    def __init__(self, events, failure=None):
        self.events = events
        self.failure = failure

    def mkdir(self, **_kwargs):
        self.events.append("mkdir")
        if self.failure:
            raise self.failure


class FakePath:
    def __init__(self, events, mkdir_failure=None, write_failure=None):
        self.events = events
        self.parent = FakeParent(events, mkdir_failure)
        self.write_failure = write_failure

    def write_bytes(self, contents):
        self.events.append(("write", contents))
        if self.write_failure:
            raise self.write_failure

    def unlink(self, missing_ok=False):
        self.events.append(("unlink", missing_ok))

    def __str__(self):
        return "fake-original-cv"


class FakeCandidatesCollection:
    def __init__(self, events, failure=None):
        self.events = events
        self.failure = failure
        self.inserted = None

    async def insert_one(self, document):
        self.events.append("insert")
        if self.failure:
            raise self.failure
        self.inserted = document


def load_upload_helpers(namespace):
    namespace.setdefault("UploadFile", object)
    namespace.setdefault("hashlib", hashlib)
    namespace.setdefault("tempfile", tempfile)
    source_path = Path(__file__).with_name("main.py")
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    wanted = {
        "validate_upload_extension",
        "save_uploaded_file_to_temp",
        "_remove_file_best_effort",
        "persist_candidate_with_original_cv",
    }
    nodes = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in wanted
    ]
    module = ast.Module(body=nodes, type_ignores=[])
    ast.fix_missing_locations(module)
    exec(compile(module, str(source_path), "exec"), namespace)
    return namespace


class UploadSafetyTests(unittest.TestCase):
    def test_validation_accepts_pdf_and_docx_and_rejects_other_types(self):
        helpers = load_upload_helpers({
            "Path": Path,
            "Optional": Optional,
            "HTTPException": FakeHTTPException,
            "ObjectId": FakeObjectId,
        })
        validate = helpers["validate_upload_extension"]

        self.assertEqual(validate("candidate.PDF"), ".pdf")
        self.assertEqual(validate("candidate.docx"), ".docx")
        with self.assertRaises(FakeHTTPException) as raised:
            validate("candidate.txt")
        self.assertEqual(raised.exception.status_code, 415)

    def test_temp_copy_reads_once_and_preserves_valid_upload_bytes(self):
        helpers = load_upload_helpers({
            "Path": Path,
            "Optional": Optional,
            "HTTPException": FakeHTTPException,
            "ObjectId": FakeObjectId,
            "hashlib": hashlib,
            "tempfile": tempfile,
            "UploadFile": object,
        })

        class FakeUpload:
            filename = "candidate.PDF"
            read_count = 0

            async def read(self):
                self.read_count += 1
                return b"exact-original-bytes"

        upload = FakeUpload()
        tmp_path, content_hash, original_bytes = asyncio.run(
            helpers["save_uploaded_file_to_temp"](upload)
        )
        try:
            self.assertEqual(upload.read_count, 1)
            self.assertEqual(Path(tmp_path).suffix, ".pdf")
            self.assertEqual(Path(tmp_path).read_bytes(), b"exact-original-bytes")
            self.assertEqual(original_bytes, b"exact-original-bytes")
            self.assertEqual(
                content_hash,
                hashlib.md5(b"exact-original-bytes").hexdigest(),
            )
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def _helpers_for(self, path, collection):
        return load_upload_helpers({
            "Path": Path,
            "Optional": Optional,
            "HTTPException": FakeHTTPException,
            "ObjectId": FakeObjectId,
            "candidate_cv_storage_key": lambda candidate_id, _filename: f"media/candidates/{candidate_id}/original.pdf",
            "resolve_candidate_cv_storage_key": lambda _key: path,
            "candidates_collection": collection,
        })

    def test_filesystem_failure_happens_before_candidate_insert(self):
        events = []
        path = FakePath(events, write_failure=OSError("disk full"))
        collection = FakeCandidatesCollection(events)
        persist = self._helpers_for(path, collection)["persist_candidate_with_original_cv"]

        with self.assertRaises(FakeHTTPException) as raised:
            asyncio.run(persist({"name": "Candidate"}, b"original", "candidate.pdf"))

        self.assertEqual(raised.exception.status_code, 500)
        self.assertNotIn("insert", events)
        self.assertIn(("unlink", True), events)

    def test_insert_failure_removes_previously_written_original(self):
        events = []
        path = FakePath(events)
        collection = FakeCandidatesCollection(events, failure=RuntimeError("database unavailable"))
        persist = self._helpers_for(path, collection)["persist_candidate_with_original_cv"]

        with self.assertRaises(RuntimeError):
            asyncio.run(persist({"name": "Candidate"}, b"original", "candidate.pdf"))

        self.assertEqual(events[:3], ["mkdir", ("write", b"original"), "insert"])
        self.assertEqual(events[-1], ("unlink", True))

    def test_success_inserts_candidate_with_original_reference(self):
        events = []
        path = FakePath(events)
        collection = FakeCandidatesCollection(events)
        persist = self._helpers_for(path, collection)["persist_candidate_with_original_cv"]

        candidate_id = asyncio.run(
            persist({"name": "Candidate"}, b"original", "candidate.pdf")
        )

        self.assertEqual(events, ["mkdir", ("write", b"original"), "insert"])
        self.assertEqual(collection.inserted["_id"], candidate_id)
        self.assertEqual(
            collection.inserted["original_cv_storage_key"],
            f"media/candidates/{candidate_id}/original.pdf",
        )


if __name__ == "__main__":
    unittest.main()
