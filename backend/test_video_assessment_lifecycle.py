import ast
import copy
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from pymongo import ReturnDocument


class UpdateResult:
    def __init__(self, modified_count=0):
        self.modified_count = modified_count


def nested_value(document, dotted_key):
    value = document
    for part in dotted_key.split("."):
        if not isinstance(value, dict) or part not in value:
            return False, None
        value = value[part]
    return True, value


def matches(document, query):
    for key, expected in query.items():
        if key == "$or":
            if not any(matches(document, clause) for clause in expected):
                return False
            continue
        exists, actual = nested_value(document, key)
        if isinstance(expected, dict):
            if "$in" in expected and actual not in expected["$in"]:
                return False
            if "$ne" in expected and actual == expected["$ne"]:
                return False
            if "$exists" in expected and exists != expected["$exists"]:
                return False
            if "$lt" in expected and (not exists or actual is None or actual >= expected["$lt"]):
                return False
        elif not exists or actual != expected:
            return False
    return True


def set_nested(document, dotted_key, value):
    target = document
    parts = dotted_key.split(".")
    for part in parts[:-1]:
        target = target.setdefault(part, {})
    target[parts[-1]] = value


def unset_nested(document, dotted_key):
    target = document
    parts = dotted_key.split(".")
    for part in parts[:-1]:
        target = target.get(part, {})
    target.pop(parts[-1], None)


class FakeCollection:
    def __init__(self, document):
        self.document = copy.deepcopy(document)

    async def find_one(self, query):
        return self.document if matches(self.document, query) else None

    async def find_one_and_update(self, query, update, return_document=None):
        if not matches(self.document, query):
            return None
        self._apply(update)
        return self.document

    async def update_one(self, query, update):
        if not matches(self.document, query):
            return UpdateResult(0)
        self._apply(update)
        return UpdateResult(1)

    def _apply(self, update):
        for key, value in update.get("$set", {}).items():
            set_nested(self.document, key, value)
        for key in update.get("$unset", {}):
            unset_nested(self.document, key)


def load_lifecycle_helpers(collection):
    source_path = Path(__file__).with_name("main.py")
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    wanted_functions = {
        "claim_video_assessment",
        "fail_video_assessment_claim",
        "release_video_assessment_claim",
        "recording_observations_from_progress",
        "response_observations_with_progress",
        "next_recording_response",
        "next_recording_work_item",
        "next_recording_stage",
        "checkpoint_response_observation",
    }
    nodes = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "VIDEO_ANALYSIS_STALE_AFTER"
            for target in node.targets
        ):
            nodes.append(node)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in wanted_functions:
            nodes.append(node)

    namespace = {
        "Optional": Optional,
        "datetime": datetime,
        "timedelta": timedelta,
        "timezone": timezone,
        "ReturnDocument": ReturnDocument,
        "interviews_collection": collection,
        "response_has_video": lambda response: bool(response.get("video_storage_key")),
        "build_unavailable_video_analysis": lambda reason, responses, status, video_available: {
            "video_analysis_status": status,
            "per_response_observations": [
                {
                    "question_index": response.get("question_index"),
                    "video_observations": {},
                }
                for response in responses
            ],
            "video_observations": {"neutral_summary": reason},
        },
    }
    module = ast.Module(body=nodes, type_ignores=[])
    ast.fix_missing_locations(module)
    exec(compile(module, str(source_path), "exec"), namespace)
    return namespace


def interview_document(**overrides):
    document = {
        "_id": "interview-1",
        "token": "token-1",
        "status": "Completed",
        "video_analysis_status": "pending",
        "assessment": None,
        "responses": [
            {
                "question_index": 0,
                "transcript": "A complete transcript remains available.",
                "video_storage_key": "media/interviews/interview-1/0.webm",
            }
        ],
    }
    document.update(overrides)
    return document


class VideoAssessmentLifecycleTests(unittest.IsolatedAsyncioTestCase):
    def test_run_function_uses_independent_head_and_speaker_stages(self):
        source_path = Path(__file__).with_name("main.py")
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        run_function = next(
            node
            for node in tree.body
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "run_claimed_video_assessment"
        )
        recording_calls = {
            nested.func.id
            for nested in ast.walk(run_function)
            if isinstance(nested, ast.Call)
            and isinstance(nested.func, ast.Name)
            and nested.func.id in {"analyze_head_pose", "analyze_speakers", "analyze_recording"}
        }
        recording_blocks = [
            node
            for node in ast.walk(run_function)
            if isinstance(node, ast.If)
            and any(
                isinstance(nested, ast.Call)
                and isinstance(nested.func, ast.Name)
                and nested.func.id in {"analyze_head_pose", "analyze_speakers"}
                for nested in ast.walk(node)
            )
        ]

        self.assertEqual(recording_calls, {"analyze_head_pose", "analyze_speakers"})
        self.assertTrue(any(isinstance(node, ast.Return) for node in ast.walk(recording_blocks[0])))

    async def test_stale_processing_claim_is_recovered_atomically(self):
        now = datetime.now(timezone.utc)
        collection = FakeCollection(
            interview_document(
                video_analysis_status="processing",
                video_analysis_started_at=now - timedelta(minutes=16),
                video_analysis_claim_id="dead-worker",
            )
        )
        helpers = load_lifecycle_helpers(collection)

        claimed = await helpers["claim_video_assessment"](
            collection.document,
            now=now,
            claim_id="retry-worker",
        )

        self.assertIsNotNone(claimed)
        self.assertEqual(claimed["video_analysis_claim_id"], "retry-worker")
        self.assertEqual(claimed["video_analysis_started_at"], now)

    async def test_legacy_processing_without_timestamp_is_recoverable(self):
        now = datetime.now(timezone.utc)
        collection = FakeCollection(interview_document(video_analysis_status="processing"))
        helpers = load_lifecycle_helpers(collection)

        claimed = await helpers["claim_video_assessment"](
            collection.document,
            now=now,
            claim_id="retry-worker",
        )

        self.assertIsNotNone(claimed)
        self.assertEqual(claimed["video_analysis_claim_id"], "retry-worker")

    async def test_fresh_processing_claim_does_not_duplicate_work(self):
        now = datetime.now(timezone.utc)
        collection = FakeCollection(
            interview_document(
                video_analysis_status="processing",
                video_analysis_started_at=now - timedelta(minutes=1),
                video_analysis_claim_id="active-worker",
            )
        )
        helpers = load_lifecycle_helpers(collection)

        claimed = await helpers["claim_video_assessment"](
            collection.document,
            now=now,
            claim_id="duplicate-worker",
        )

        self.assertIsNone(claimed)
        self.assertEqual(collection.document["video_analysis_claim_id"], "active-worker")

    async def test_checkpoint_releases_claim_and_next_question_can_continue_immediately(self):
        now = datetime.now(timezone.utc)
        responses = [
            {"question_index": index, "transcript": f"Answer {index}"}
            for index in range(5)
        ]
        collection = FakeCollection(
            interview_document(
                responses=responses,
                video_analysis_status="processing",
                video_analysis_claim_id="q0-worker",
                video_analysis_started_at=now,
            )
        )
        helpers = load_lifecycle_helpers(collection)
        timestamped_observation = {
            "head_orientation": {
                "status": "completed",
                "head_observation_intervals": [
                    {"type": "face_absent", "start_seconds": 22.6, "end_seconds": 24.7}
                ],
                "rapid_movement_events": [
                    {"movement_type": "yaw", "time_seconds": 27.3, "delta_degrees": 31.0}
                ],
            },
            "speaker_observations": {
                "status": "completed",
                "possible_second_speaker_intervals": [
                    {"speaker_label": "SPEAKER_00", "start_seconds": 2.0, "end_seconds": 5.0}
                ],
                "overlapping_speech_intervals": [
                    {"start_seconds": 24.5, "end_seconds": 26.8}
                ],
            },
        }

        released = await helpers["release_video_assessment_claim"](
            token="token-1",
            claim_id="q0-worker",
            stage="recording_observation_0_completed",
            next_stage="recording_observation_1",
            checkpoint={
                "video_analysis_progress.recording_observations_by_question.0": timestamped_observation
            },
        )

        self.assertEqual(released["video_analysis_status"], "pending")
        self.assertNotIn("video_analysis_claim_id", released)
        stored = helpers["recording_observations_from_progress"](released)
        self.assertEqual(stored[0], timestamped_observation)
        self.assertEqual(helpers["next_recording_response"](responses, stored)["question_index"], 1)

        next_claim = await helpers["claim_video_assessment"](
            released,
            now=now + timedelta(seconds=1),
            claim_id="q1-worker",
        )
        self.assertIsNotNone(next_claim)
        self.assertEqual(next_claim["video_analysis_claim_id"], "q1-worker")

    def test_five_question_progress_runs_all_heads_before_speakers(self):
        collection = FakeCollection(interview_document())
        helpers = load_lifecycle_helpers(collection)
        responses = [{"question_index": index} for index in range(5)]
        completed = {}
        observed_order = []

        for _ in range(10):
            stage, response = helpers["next_recording_work_item"](responses, completed)
            observed_order.append((stage, response["question_index"]))
            observation = completed.setdefault(response["question_index"], {})
            observation[
                "head_orientation" if stage == "head" else "speaker_observations"
            ] = {}

        self.assertEqual(
            observed_order,
            [("head", question) for question in range(5)]
            + [("speaker", question) for question in range(5)],
        )
        self.assertIsNone(helpers["next_recording_response"](responses, completed))

    def test_head_checkpoint_is_visible_while_speaker_is_pending(self):
        collection = FakeCollection(interview_document())
        helpers = load_lifecycle_helpers(collection)
        responses = [{"question_index": 0, "video_observations": {"notes": ["kept"]}}]
        head = {
            "status": "completed",
            "head_observation_intervals": [
                {"type": "face_absent", "start_seconds": 1.0, "end_seconds": 3.2}
            ],
            "rapid_movement_events": [
                {"movement_type": "yaw", "time_seconds": 4.1}
            ],
        }

        helpers["checkpoint_response_observation"](
            responses, 0, "head_orientation", head
        )

        self.assertEqual(responses[0]["video_observations"]["head_orientation"], head)
        self.assertEqual(responses[0]["video_observations"]["notes"], ["kept"])
        work = helpers["next_recording_work_item"](
            responses, {0: {"head_orientation": head}}
        )
        self.assertEqual((work[0], work[1]["question_index"]), ("speaker", 0))

        recruiter_payload = helpers["response_observations_with_progress"](
            {"question_index": 0}, {0: {"head_orientation": head}}
        )
        self.assertEqual(recruiter_payload["head_orientation"], head)
        self.assertNotIn("speaker_observations", recruiter_payload)

    def test_speaker_retry_does_not_erase_completed_head_checkpoint(self):
        collection = FakeCollection(interview_document())
        helpers = load_lifecycle_helpers(collection)
        head = {"status": "completed", "head_observation_intervals": [{"start_seconds": 2.0}]}
        progress = {0: {"head_orientation": head}}

        first = helpers["next_recording_work_item"](
            [{"question_index": 0}], progress
        )
        second = helpers["next_recording_work_item"](
            [{"question_index": 0}], progress
        )

        self.assertEqual(first[0], "speaker")
        self.assertEqual(second[0], "speaker")
        self.assertEqual(progress[0]["head_orientation"], head)

    async def test_speaker_failure_releases_claim_without_erasing_head_timestamp(self):
        head = {
            "status": "completed",
            "head_observation_intervals": [
                {"type": "face_absent", "start_seconds": 8.0, "end_seconds": 10.5}
            ],
        }
        response = {
            "question_index": 0,
            "transcript": "Preserved transcript",
            "video_storage_key": "media/interviews/interview-1/0.webm",
            "video_observations": {"head_orientation": head},
        }
        collection = FakeCollection(
            interview_document(
                responses=[response],
                assessment={"overall_interview_score": 80},
                video_analysis_status="processing",
                video_analysis_claim_id="speaker-worker",
                video_analysis_progress={
                    "recording_observations_by_question": {
                        "0": {"head_orientation": head}
                    }
                },
            )
        )
        helpers = load_lifecycle_helpers(collection)

        await helpers["fail_video_assessment_claim"](
            token="token-1",
            claim_id="speaker-worker",
            responses=[response],
            error=TimeoutError("speaker stage exceeded its execution window"),
        )

        stored_head = collection.document["video_analysis_progress"][
            "recording_observations_by_question"
        ]["0"]["head_orientation"]
        self.assertEqual(stored_head, head)
        self.assertEqual(
            collection.document["responses"][0]["video_observations"]["head_orientation"],
            head,
        )

    async def test_exception_releases_claim_and_preserves_completed_answer_score(self):
        assessment = {"overall_interview_score": 82, "summary": "Completed answer score."}
        collection = FakeCollection(
            interview_document(
                video_analysis_status="processing",
                video_analysis_claim_id="active-worker",
                assessment=assessment,
            )
        )
        helpers = load_lifecycle_helpers(collection)

        await helpers["fail_video_assessment_claim"](
            token="token-1",
            claim_id="active-worker",
            responses=collection.document["responses"],
            error=RuntimeError("optional observation failed"),
        )

        self.assertEqual(collection.document["video_analysis_status"], "failed")
        self.assertEqual(collection.document["assessment"], assessment)
        self.assertEqual(
            collection.document["responses"][0]["transcript"],
            "A complete transcript remains available.",
        )
        self.assertNotIn("video_analysis_claim_id", collection.document)
        self.assertEqual(collection.document["video_analysis"]["video_analysis_status"], "failed")


if __name__ == "__main__":
    unittest.main()
