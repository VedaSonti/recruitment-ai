import ast
import re
import unittest
from pathlib import Path


def load_video_helpers():
    source_path = Path(__file__).with_name("main.py")
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    helper_names = {
        "count_filler_words",
        "clamp_percentage",
        "optional_number",
        "optional_int",
        "safe_quality",
        "safe_noise",
        "contains_prohibited_video_observation_term",
        "sanitize_video_observation_text",
        "sanitize_video_observation_list",
        "base_response_video_observations",
        "build_unavailable_video_analysis",
        "normalize_video_analysis_payload",
        "apply_video_observations_to_responses",
    }
    assignment_names = {
        "VIDEO_QUALITY_VALUES",
        "VIDEO_NOISE_VALUES",
        "VIDEO_ANALYSIS_STATUSES",
        "FILLER_WORDS",
        "FILLER_PHRASES",
        "PROHIBITED_VIDEO_OBSERVATION_TERMS",
    }
    nodes = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets = [target.id for target in node.targets if isinstance(target, ast.Name)]
            if any(target in assignment_names for target in targets):
                nodes.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in helper_names:
            nodes.append(node)

    module = ast.Module(body=nodes, type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {"re": re}
    exec(compile(module, str(source_path), "exec"), namespace)
    return namespace


helpers = load_video_helpers()
normalize_video_analysis_payload = helpers["normalize_video_analysis_payload"]
build_unavailable_video_analysis = helpers["build_unavailable_video_analysis"]
apply_video_observations_to_responses = helpers["apply_video_observations_to_responses"]
contains_prohibited_video_observation_term = helpers["contains_prohibited_video_observation_term"]


def sample_response(transcript="I built the API, um, and tested the deployment."):
    return {
        "question_index": 0,
        "question": "Tell us about the project.",
        "transcript": transcript,
    }


def sample_raw(**overrides):
    raw = {
        "video_observations": {
            "recording_quality": {
                "video_available": True,
                "audio_available": True,
                "face_visible_percentage": 94,
                "multiple_faces_detected": False,
                "lighting": "good",
                "framing": "good",
                "audio_clarity": "good",
                "background_noise": "low",
            },
            "delivery_observations": {
                "speaking_time_seconds": 27.4,
                "estimated_words_per_minute": 126,
                "filler_word_count": 3,
                "long_pause_count": 2,
                "longest_pause_seconds": 4.1,
                "response_completed_within_limit": True,
                "screen_direction_percentage": 72,
            },
            "technical_observations": ["Audio was clear."],
            "neutral_summary": "The candidate remained visible for most of the response.",
        },
        "per_response_observations": [
            {
                "question_index": 0,
                "video_observations": {
                    "face_visible_percentage": 91,
                    "speaking_time_seconds": 29.2,
                    "filler_word_count": 2,
                    "long_pause_count": 1,
                    "longest_pause_seconds": 3.2,
                    "response_completed_within_limit": True,
                    "screen_direction_percentage": 70,
                    "notes": ["Audio was clear."],
                },
            }
        ],
    }
    for dotted_key, value in overrides.items():
        target = raw
        parts = dotted_key.split("__")
        for part in parts[:-1]:
            target = target[part]
        target[parts[-1]] = value
    return raw


class VideoObservationSafetyTests(unittest.TestCase):
    def test_normal_visible_candidate_with_clear_audio(self):
        result = normalize_video_analysis_payload(sample_raw(), [sample_response()])
        quality = result["video_observations"]["recording_quality"]
        self.assertEqual(result["video_analysis_status"], "completed")
        self.assertTrue(quality["video_available"])
        self.assertEqual(quality["audio_clarity"], "good")
        self.assertEqual(quality["face_visible_percentage"], 94)

    def test_stored_frames_cannot_be_reported_as_video_unavailable(self):
        result = normalize_video_analysis_payload(
            sample_raw(video_observations__recording_quality__video_available=False),
            [sample_response()],
        )
        self.assertEqual(result["video_analysis_status"], "completed")
        self.assertTrue(
            result["video_observations"]["recording_quality"]["video_available"]
        )

    def test_candidate_briefly_moves_out_of_frame(self):
        result = normalize_video_analysis_payload(
            sample_raw(video_observations__technical_observations=["Candidate moved partially out of frame once."]),
            [sample_response()],
        )
        self.assertIn(
            "Candidate moved partially out of frame once.",
            result["video_observations"]["technical_observations"],
        )

    def test_no_face_visible(self):
        result = normalize_video_analysis_payload(
            sample_raw(video_observations__recording_quality__face_visible_percentage=0),
            [sample_response()],
        )
        self.assertEqual(result["video_observations"]["recording_quality"]["face_visible_percentage"], 0)

    def test_more_than_one_face_appears(self):
        result = normalize_video_analysis_payload(
            sample_raw(video_observations__recording_quality__multiple_faces_detected=True),
            [sample_response()],
        )
        self.assertTrue(result["video_observations"]["recording_quality"]["multiple_faces_detected"])

    def test_audio_only_and_no_video(self):
        result = build_unavailable_video_analysis("No sampled video frames were available.", [sample_response()])
        quality = result["video_observations"]["recording_quality"]
        self.assertEqual(result["video_analysis_status"], "unavailable")
        self.assertFalse(quality["video_available"])
        self.assertTrue(quality["audio_available"])

    def test_poor_lighting(self):
        result = normalize_video_analysis_payload(
            sample_raw(video_observations__recording_quality__lighting="poor"),
            [sample_response()],
        )
        self.assertEqual(result["video_observations"]["recording_quality"]["lighting"], "poor")

    def test_high_background_noise(self):
        result = normalize_video_analysis_payload(
            sample_raw(video_observations__recording_quality__background_noise="high"),
            [sample_response()],
        )
        self.assertEqual(result["video_observations"]["recording_quality"]["background_noise"], "high")

    def test_answer_exceeds_30_seconds_flag_can_be_false(self):
        result = normalize_video_analysis_payload(
            sample_raw(video_observations__delivery_observations__response_completed_within_limit=False),
            [sample_response()],
        )
        self.assertFalse(result["video_observations"]["delivery_observations"]["response_completed_within_limit"])

    def test_empty_transcript(self):
        result = build_unavailable_video_analysis("No sampled video frames were available.", [sample_response("")])
        self.assertEqual(result["per_response_observations"][0]["video_observations"]["filler_word_count"], 0)

    def test_video_processing_fails_while_transcript_scoring_can_succeed(self):
        result = build_unavailable_video_analysis("Video observations could not be completed because processing failed.", [sample_response()], status="failed")
        self.assertEqual(result["video_analysis_status"], "failed")
        self.assertIn("video_observations", result)

    def test_video_recorded_but_frame_analysis_failed(self):
        result = build_unavailable_video_analysis(
            "Video recorded, but visual frame analysis failed.",
            [sample_response()],
            status="failed",
            video_available=True,
        )
        quality = result["video_observations"]["recording_quality"]
        self.assertEqual(result["video_analysis_status"], "failed")
        self.assertTrue(quality["video_available"])
        self.assertIn(
            "Video recorded, but visual frame analysis failed.",
            result["video_observations"]["neutral_summary"],
        )

    def test_refresh_repeatedly_is_guarded_by_processing_status(self):
        source = Path(__file__).with_name("main.py").read_text(encoding="utf-8")
        self.assertIn('interview.get("video_analysis_status") == "processing"', source)

    def test_completed_assessment_is_not_regenerated(self):
        source = Path(__file__).with_name("main.py").read_text(encoding="utf-8")
        self.assertIn('"message": "Already assessed"', source)

    def test_no_prohibited_labels_in_generated_video_observation_output(self):
        result = normalize_video_analysis_payload(
            sample_raw(
                video_observations__technical_observations=["Candidate looked nervous and dishonest."],
                video_observations__neutral_summary="Candidate seemed confident.",
            ),
            [sample_response()],
        )
        strings = []

        def collect(value):
            if isinstance(value, dict):
                for key, nested in value.items():
                    strings.append(str(key))
                    collect(nested)
            elif isinstance(value, list):
                for nested in value:
                    collect(nested)
            elif isinstance(value, str):
                strings.append(value)

        collect(result)
        joined = " ".join(strings).lower()
        self.assertFalse(contains_prohibited_video_observation_term(joined))
        self.assertNotIn("confidence_score", joined)
        self.assertNotIn("behaviour_score", joined)


if __name__ == "__main__":
    unittest.main()
