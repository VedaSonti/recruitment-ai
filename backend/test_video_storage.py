import ast
import re
import tempfile
import unittest
from pathlib import Path, PurePosixPath


class HTTPException(Exception):
    def __init__(self, status_code, detail):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def load_video_storage_helpers(media_root: Path):
    source_path = Path(__file__).with_name("main.py")
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    helper_names = {
        "interview_video_storage_key",
        "resolve_interview_video_storage_key",
        "resolve_stored_interview_video_path",
        "validate_uploaded_interview_video_key",
        "response_has_video",
        "response_video_playback",
        "parse_byte_range",
    }
    nodes = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in helper_names
    ]

    module = ast.Module(body=nodes, type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {
        "HTTPException": HTTPException,
        "INTERVIEW_MEDIA_ROOT": media_root,
        "INTERVIEW_VIDEO_KEY_PREFIX": PurePosixPath("media/interviews"),
        "Optional": __import__("typing").Optional,
        "Path": Path,
        "PurePosixPath": PurePosixPath,
        "re": re,
        "VERCEL_BLOB_STORAGE_BACKEND": "vercel_blob",
    }
    exec(compile(module, str(source_path), "exec"), namespace)
    return namespace


class VideoStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.media_root = Path(self.temp_dir.name) / "media" / "interviews"
        self.helpers = load_video_storage_helpers(self.media_root)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_storage_key_is_portable_and_resolves_inside_media_root(self):
        storage_key = self.helpers["interview_video_storage_key"](
            "6a683d3dd22f99f70063f616",
            2,
        )
        resolved = self.helpers["resolve_interview_video_storage_key"](storage_key)

        self.assertEqual(
            storage_key,
            "media/interviews/6a683d3dd22f99f70063f616/2.webm",
        )
        self.assertFalse(Path(storage_key).is_absolute())
        self.assertEqual(
            resolved,
            (
                self.media_root
                / "6a683d3dd22f99f70063f616"
                / "2.webm"
            ).resolve(),
        )

    def test_path_traversal_and_absolute_paths_are_rejected(self):
        resolve = self.helpers["resolve_interview_video_storage_key"]
        unsafe_keys = [
            "../outside.webm",
            "media/interviews/../outside.webm",
            "media/interviews/6a683d3dd22f99f70063f616/../../outside.webm",
            "/media/interviews/6a683d3dd22f99f70063f616/0.webm",
            "C:\\media\\interviews\\6a683d3dd22f99f70063f616\\0.webm",
            "media/interviews/not-an-object-id/0.webm",
            "media/interviews/6a683d3dd22f99f70063f616/not-video.txt",
        ]

        for storage_key in unsafe_keys:
            with self.subTest(storage_key=storage_key):
                self.assertIsNone(resolve(storage_key))

    def test_direct_blob_key_must_match_current_interview_and_question(self):
        validate = self.helpers["validate_uploaded_interview_video_key"]
        interview_id = "6a683d3dd22f99f70063f616"
        self.assertTrue(validate(
            f"media/interviews/{interview_id}/2-randomSuffix.webm",
            interview_id,
            2,
        ))
        self.assertFalse(validate(
            f"media/interviews/{interview_id}/1-randomSuffix.webm",
            interview_id,
            2,
        ))
        self.assertFalse(validate(
            "media/interviews/aaaaaaaaaaaaaaaaaaaaaaaa/2-randomSuffix.webm",
            interview_id,
            2,
        ))

    def test_playback_url_is_returned_only_when_file_exists(self):
        storage_key = "media/interviews/6a683d3dd22f99f70063f616/0.webm"
        response = {
            "question_index": 0,
            "video_storage_key": storage_key,
            "video_content_type": "video/webm",
        }
        playback = self.helpers["response_video_playback"]

        self.assertEqual(playback("match123", response), (None, "missing"))

        video_path = self.helpers["resolve_interview_video_storage_key"](storage_key)
        video_path.parent.mkdir(parents=True, exist_ok=True)
        video_path.write_bytes(b"test-video")
        original_stat = video_path.stat()

        expected = (
            "/interviews/by-match/match123/responses/0/video",
            "available",
        )
        self.assertEqual(playback("match123", response), expected)
        self.assertEqual(playback("match123", response), expected)
        repeated_stat = video_path.stat()
        self.assertEqual(repeated_stat.st_size, original_stat.st_size)
        self.assertEqual(repeated_stat.st_mtime_ns, original_stat.st_mtime_ns)
        self.assertEqual(len(list(video_path.parent.glob("*.webm"))), 1)

    def test_historical_upload_is_not_resolved_from_legacy_absolute_path(self):
        response = {
            "question_index": 0,
            "video_path": r"C:\old-machine\temporary\answer.webm",
            "frames_b64": ["sampled-frame"],
        }

        self.assertIsNone(
            self.helpers["resolve_stored_interview_video_path"](response)
        )
        self.assertEqual(
            self.helpers["response_video_playback"]("match123", response),
            (None, "historical_unavailable"),
        )

    def test_private_blob_playback_is_available_without_a_local_file(self):
        response = {
            "question_index": 0,
            "video_storage_key": (
                "media/interviews/6a683d3dd22f99f70063f616/0-random.webm"
            ),
            "video_storage_backend": "vercel_blob",
        }
        self.assertEqual(
            self.helpers["response_video_playback"]("match123", response),
            (
                "/interviews/by-match/match123/responses/0/video",
                "available",
            ),
        )

    def test_byte_ranges_support_standard_open_and_suffix_forms(self):
        parse = self.helpers["parse_byte_range"]
        self.assertEqual(parse("bytes=10-19", 100), (10, 19))
        self.assertEqual(parse("bytes=90-", 100), (90, 99))
        self.assertEqual(parse("bytes=-10", 100), (90, 99))
        self.assertIsNone(parse(None, 100))

    def test_existing_legacy_file_is_supported_only_inside_media_root(self):
        video_path = (
            self.media_root / "6a683d3dd22f99f70063f616" / "0.webm"
        )
        video_path.parent.mkdir(parents=True, exist_ok=True)
        video_path.write_bytes(b"legacy-video")
        response = {
            "question_index": 0,
            "video_path": str(video_path),
            "frames_b64": ["sampled-frame"],
        }

        self.assertEqual(
            self.helpers["resolve_stored_interview_video_path"](response),
            video_path.resolve(),
        )
        self.assertEqual(
            self.helpers["response_video_playback"]("match123", response),
            (
                "/interviews/by-match/match123/responses/0/video",
                "available",
            ),
        )

    def test_audio_only_response_is_not_marked_as_video(self):
        response = {
            "question_index": 0,
            "question": "Question",
            "transcript": "Answer",
        }

        self.assertFalse(self.helpers["response_has_video"](response))
        self.assertEqual(
            self.helpers["response_video_playback"]("match123", response),
            (None, "not_recorded"),
        )

    def test_mongodb_response_uses_storage_key_not_absolute_video_path(self):
        source = Path(__file__).with_name("main.py").read_text(encoding="utf-8")
        self.assertIn('"video_storage_key": video_storage_key', source)
        self.assertNotIn('"video_path": str(persisted_video_path)', source)


if __name__ == "__main__":
    unittest.main()
