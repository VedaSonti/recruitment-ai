import ast
import copy
import hashlib
import os
import sys
import tempfile
import types
import unittest
import warnings
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

import recording_observations as observations
from recording_observations import (
    OBSERVATION_SCHEMA_VERSION,
    ObservationConfig,
    aggregate_diarization_segments,
    aggregate_head_pose_samples,
    unavailable_recording_observations,
)


CONFIG = ObservationConfig(
    head_sample_fps=2.0,
    head_down_pitch_threshold_degrees=18.0,
    head_down_min_duration_seconds=2.0,
    head_movement_delta_threshold_degrees=25.0,
    head_movement_window_seconds=0.75,
    face_absent_min_duration_seconds=2.0,
    min_valid_face_frames=5,
    min_face_coverage_percent=30.0,
    toward_screen_yaw_degrees=22.0,
    toward_screen_pitch_degrees=22.0,
    min_secondary_speaker_seconds=1.5,
    min_speaker_segment_seconds=0.5,
    min_total_speech_seconds=2.0,
    speaker_confidence_threshold=0.65,
)


def face_samples(pitches, yaws=None, rolls=None):
    yaws = yaws or [0.0] * len(pitches)
    rolls = rolls or [0.0] * len(pitches)
    return [
        {
            "time_seconds": index * 0.5,
            "face_count": 1,
            "pitch": pitch,
            "yaw": yaws[index],
            "roll": rolls[index],
        }
        for index, pitch in enumerate(pitches)
    ]


def speaker_segment(start, end, label):
    return {
        "start_seconds": start,
        "end_seconds": end,
        "speaker_label": label,
    }


def load_merge_function():
    source = Path(__file__).with_name("main.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    function = next(
        node for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "merge_recording_observations"
    )
    namespace = {
        "OBSERVATION_SCHEMA_VERSION": OBSERVATION_SCHEMA_VERSION,
        "unavailable_recording_observations": unavailable_recording_observations,
        "base_response_video_observations": lambda response: {"notes": []},
    }
    exec(compile(ast.Module(body=[function], type_ignores=[]), "main.py", "exec"), namespace)
    return namespace["merge_recording_observations"]


class HeadOrientationTests(unittest.TestCase):
    def test_official_face_landmarker_model_is_packaged(self):
        model_path = observations.face_landmarker_model_path()
        self.assertTrue(model_path.is_file())
        self.assertEqual(
            hashlib.sha256(model_path.read_bytes()).hexdigest(),
            "64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff",
        )

    def test_missing_mediapipe_package_is_explicit(self):
        fake_cv2 = types.ModuleType("cv2")
        with patch.dict(sys.modules, {"cv2": fake_cv2, "mediapipe": None}):
            result = observations.analyze_head_pose("recording.webm", CONFIG)
        self.assertEqual(result["status"], "model_unavailable")
        self.assertIn("package is missing", result["status_reason"])

    def test_stable_forward_facing_candidate(self):
        result = aggregate_head_pose_samples(face_samples([2.0] * 10), CONFIG)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["candidate_visible"], "true")
        self.assertEqual(result["rapid_movement_count"], 0)
        self.assertFalse(result["sustained_downward_observed"])
        self.assertEqual(result["mainly_toward_screen"], "yes")

    def test_brief_downward_position_is_not_sustained(self):
        result = aggregate_head_pose_samples(face_samples([0, 0, 25, 0, 0, 0, 0, 0]), CONFIG)
        self.assertEqual(result["downward_frame_count"], 1)
        self.assertFalse(result["sustained_downward_observed"])

    def test_sustained_downward_interval_is_reported(self):
        result = aggregate_head_pose_samples(face_samples([0, 0, 25, 25, 25, 25, 25, 0]), CONFIG)
        self.assertTrue(result["sustained_downward_observed"])
        self.assertGreaterEqual(result["longest_downward_interval_seconds"], 2.0)
        self.assertEqual(result["head_observation_intervals"][0]["type"], "sustained_downward_orientation")

    def test_rapid_head_movement_is_timestamped(self):
        result = aggregate_head_pose_samples(
            face_samples([0] * 8, yaws=[0, 35, 0, 35, 0, 35, 0, 0]), CONFIG
        )
        self.assertGreater(result["rapid_movement_count"], 0)
        self.assertEqual(result["rapid_movement_events"][0]["movement_type"], "yaw")

    def test_face_leaves_frame_for_sustained_interval(self):
        samples = face_samples([0] * 4)
        samples += [{"time_seconds": 2 + index * 0.5, "face_count": 0} for index in range(5)]
        samples += [dict(face_samples([0])[0], time_seconds=4.5)]
        result = aggregate_head_pose_samples(samples, CONFIG)
        self.assertTrue(result["candidate_left_frame"])
        self.assertGreaterEqual(result["longest_face_absent_interval_seconds"], 2.0)
        self.assertTrue(any(item["type"] == "face_absent" for item in result["head_observation_intervals"]))

    def test_no_visible_face_returns_explained_insufficient_status(self):
        samples = [{"time_seconds": index * 0.5, "face_count": 0} for index in range(10)]
        result = aggregate_head_pose_samples(samples, CONFIG)
        self.assertEqual(result["status"], "insufficient_frames")
        self.assertEqual(result["candidate_visible"], "false")
        self.assertIn("Insufficient clear face frames", result["status_reason"])

    def test_multiple_faces_remains_observable(self):
        samples = face_samples([0] * 8)
        samples.append({"time_seconds": 4.0, "face_count": 2})
        result = aggregate_head_pose_samples(samples, CONFIG)
        self.assertTrue(result["multiple_faces_detected"])

    def test_missing_face_landmarker_model_is_explicit(self):
        fake_cv2 = types.ModuleType("cv2")
        fake_mp = types.ModuleType("mediapipe")
        with patch.dict(sys.modules, {"cv2": fake_cv2, "mediapipe": fake_mp}), patch.object(
            observations, "face_landmarker_model_path", return_value=Path("missing-face-landmarker.task")
        ):
            result = observations.analyze_head_pose("recording.webm", CONFIG)
        self.assertEqual(result["status"], "model_unavailable")
        self.assertIn("model is not installed", result["status_reason"])

    def test_face_model_load_failure_is_explicit(self):
        fake_vision = types.SimpleNamespace(
            RunningMode=types.SimpleNamespace(VIDEO="VIDEO"),
            FaceLandmarkerOptions=lambda **kwargs: kwargs,
            FaceLandmarker=types.SimpleNamespace(
                create_from_options=lambda options: (_ for _ in ()).throw(RuntimeError("load failed"))
            ),
        )
        fake_mp = types.ModuleType("mediapipe")
        fake_mp.tasks = types.SimpleNamespace(
            vision=fake_vision, BaseOptions=lambda **kwargs: kwargs
        )
        fake_cv2 = types.ModuleType("cv2")
        fake_cv2.VideoCapture = lambda path: types.SimpleNamespace(isOpened=lambda: True, release=lambda: None)
        with tempfile.NamedTemporaryFile(suffix=".task") as model_file, patch.dict(
            sys.modules, {"cv2": fake_cv2, "mediapipe": fake_mp}
        ), patch.object(
            observations, "face_landmarker_model_path", return_value=Path(model_file.name)
        ):
            result = observations.analyze_head_pose("recording.webm", CONFIG)
        self.assertEqual(result["status"], "model_unavailable")
        self.assertIn("could not be loaded", result["status_reason"])

    def test_face_landmarker_successfully_analyzes_a_visible_frame(self):
        landmarks = [types.SimpleNamespace(x=0.5, y=0.5) for _ in range(300)]

        class FakeLandmarker:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def detect_for_video(self, _image, _timestamp_ms):
                return types.SimpleNamespace(face_landmarks=[landmarks])

        class FakeCapture:
            def __init__(self):
                self.frames = [observations.np.zeros((10, 10, 3), dtype=observations.np.uint8)]

            def isOpened(self):
                return True

            def read(self):
                return (True, self.frames.pop(0)) if self.frames else (False, None)

            def get(self, _property):
                return 0.0

            def release(self):
                return None

        fake_vision = types.SimpleNamespace(
            RunningMode=types.SimpleNamespace(VIDEO="VIDEO"),
            FaceLandmarkerOptions=lambda **kwargs: kwargs,
            FaceLandmarker=types.SimpleNamespace(
                create_from_options=lambda _options: FakeLandmarker()
            ),
        )
        fake_mp = types.ModuleType("mediapipe")
        fake_mp.tasks = types.SimpleNamespace(
            vision=fake_vision,
            BaseOptions=lambda **kwargs: kwargs,
        )
        fake_mp.Image = lambda **kwargs: kwargs
        fake_mp.ImageFormat = types.SimpleNamespace(SRGB="SRGB")
        fake_cv2 = types.ModuleType("cv2")
        fake_cv2.CAP_PROP_POS_MSEC = 0
        fake_cv2.COLOR_BGR2RGB = 1
        fake_cv2.SOLVEPNP_ITERATIVE = 0
        fake_cv2.VideoCapture = lambda _path: FakeCapture()
        fake_cv2.cvtColor = lambda frame, _conversion: frame
        fake_cv2.solvePnP = lambda *_args, **_kwargs: (
            True,
            observations.np.zeros((3, 1)),
            None,
        )
        successful_config = replace(CONFIG, min_valid_face_frames=1)

        with tempfile.NamedTemporaryFile(suffix=".task") as model_file, patch.dict(
            sys.modules, {"cv2": fake_cv2, "mediapipe": fake_mp}
        ), patch.object(
            observations, "face_landmarker_model_path", return_value=Path(model_file.name)
        ), patch.object(
            observations, "_rotation_angles", return_value=(0.0, 0.0, 0.0)
        ):
            result = observations.analyze_head_pose("recording.webm", successful_config)

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["sampled_frame_count"], 1)
        self.assertEqual(result["valid_face_frame_count"], 1)


class SpeakerDiarizationTests(unittest.TestCase):
    def test_ffmpeg_unavailable_is_explicit(self):
        with patch.object(
            observations, "_resolve_ffmpeg_executable", return_value=None
        ):
            result = observations.analyze_speakers("recording.webm", CONFIG)
        self.assertEqual(result["status"], "model_unavailable")
        self.assertIn("FFmpeg is unavailable", result["status_reason"])

    def test_ffmpeg_resolver_falls_back_to_packaged_binary(self):
        fake_imageio_ffmpeg = types.ModuleType("imageio_ffmpeg")
        fake_imageio_ffmpeg.get_ffmpeg_exe = lambda: "/var/task/ffmpeg-linux-x86_64"
        with patch.object(observations.shutil, "which", return_value=None), patch.dict(
            sys.modules, {"imageio_ffmpeg": fake_imageio_ffmpeg}
        ):
            executable = observations._resolve_ffmpeg_executable()
        self.assertEqual(executable, "/var/task/ffmpeg-linux-x86_64")

    def test_successful_audio_extraction_uses_resolved_ffmpeg(self):
        completed_process = types.SimpleNamespace(returncode=0)
        run = Mock(return_value=completed_process)
        pipeline = Mock(return_value="diarization-output")
        with patch.object(
            observations,
            "_resolve_ffmpeg_executable",
            return_value="/var/task/ffmpeg-linux-x86_64",
        ), patch.object(
            observations, "_package_available", return_value=True
        ), patch.object(
            observations.subprocess, "run", run
        ), patch.object(
            observations,
            "_load_pcm_waveform",
            return_value=({"waveform": "samples", "sample_rate": 16000}, 30.0),
        ), patch.object(
            observations, "_load_speaker_pipeline", return_value=pipeline
        ), patch.object(
            observations,
            "_diarization_segments",
            return_value=[speaker_segment(0, 29.0, "SPEAKER_00")],
        ), patch.dict(
            os.environ, {"HUGGINGFACE_TOKEN": "test-token"}, clear=False
        ):
            result = observations.analyze_speakers("recording.webm", CONFIG)

        command = run.call_args.args[0]
        self.assertEqual(command[0], "/var/task/ffmpeg-linux-x86_64")
        self.assertEqual(command[command.index("-ac") + 1], "1")
        self.assertEqual(command[command.index("-ar") + 1], "16000")
        self.assertEqual(command[command.index("-c:a") + 1], "pcm_s16le")
        pipeline.assert_called_once_with(
            {"waveform": "samples", "sample_rate": 16000}
        )
        self.assertEqual(result["status"], "completed")

    def test_pcm_waveform_loading_avoids_torchcodec(self):
        class FakeTensor:
            def unsqueeze(self, dimension):
                self.dimension = dimension
                return self

        fake_torch = types.ModuleType("torch")
        fake_torch.from_numpy = lambda samples: FakeTensor()
        with tempfile.TemporaryDirectory() as directory:
            audio_path = Path(directory) / "recording.wav"
            with observations.wave.open(str(audio_path), "wb") as target:
                target.setnchannels(1)
                target.setsampwidth(2)
                target.setframerate(16000)
                target.writeframes(b"\x00\x00" * 32000)
            with patch.dict(sys.modules, {"torch": fake_torch}):
                waveform, duration = observations._load_pcm_waveform(str(audio_path))
        self.assertEqual(waveform["sample_rate"], 16000)
        self.assertEqual(waveform["waveform"].dimension, 0)
        self.assertAlmostEqual(duration, 2.0)

    def test_speaker_pipeline_is_loaded_and_calibrated_once(self):
        class FakeEmbedding:
            reads = 0

            @property
            def min_num_samples(self):
                self.reads += 1
                warnings.warn_explicit(
                    "std(): degrees of freedom is <= 0. test",
                    UserWarning,
                    "pooling.py",
                    93,
                    module="pyannote.audio.models.blocks.pooling",
                )
                return 640

        pipeline = types.SimpleNamespace(_embedding=FakeEmbedding())
        fake_pipeline_class = types.SimpleNamespace(
            from_pretrained=Mock(return_value=pipeline)
        )
        fake_huggingface_hub = types.ModuleType("huggingface_hub")
        fake_huggingface_hub.snapshot_download = Mock(return_value="/tmp/test-model")
        with patch.object(
            observations, "_speaker_pipeline", None
        ), patch.object(
            observations, "_speaker_pipeline_model", None
        ), patch.object(
            observations,
            "_import_speaker_pipeline_class",
            return_value=fake_pipeline_class,
        ), patch.dict(
            sys.modules, {"huggingface_hub": fake_huggingface_hub}
        ), patch.dict(
            os.environ,
            {
                "HUGGINGFACE_TOKEN": "test-token",
                "SPEAKER_DIARIZATION_MODEL": "test-model",
                "SPEAKER_DIARIZATION_DEVICE": "cpu",
            },
            clear=False,
        ), warnings.catch_warnings(record=True) as caught:
            first = observations._load_speaker_pipeline()
            second = observations._load_speaker_pipeline()

        self.assertIs(first, pipeline)
        self.assertIs(second, pipeline)
        fake_pipeline_class.from_pretrained.assert_called_once()
        fake_huggingface_hub.snapshot_download.assert_called_once_with(
            repo_id="test-model", token="test-token"
        )
        self.assertEqual(pipeline._embedding.reads, 1)
        self.assertFalse(any("degrees of freedom" in str(item.message) for item in caught))

    def test_recording_shorter_than_minimum_skips_model_inference(self):
        with patch.object(observations.shutil, "which", return_value="ffmpeg"), patch.object(
            observations, "_package_available", return_value=True
        ), patch.object(
            observations.subprocess, "run", return_value=types.SimpleNamespace(returncode=0)
        ), patch.object(
            observations,
            "_load_pcm_waveform",
            return_value=({"waveform": "test", "sample_rate": 16000}, 1.0),
        ), patch.object(
            observations, "_load_speaker_pipeline"
        ) as load_pipeline, patch.dict(
            os.environ, {"HUGGINGFACE_TOKEN": "test-token"}, clear=False
        ):
            result = observations.analyze_speakers("recording.webm", CONFIG)

        self.assertEqual(result["status"], "insufficient_audio")
        load_pipeline.assert_not_called()

    def test_recording_uses_only_in_memory_waveform_for_inference(self):
        pipeline = Mock(return_value=[])
        waveform = {"waveform": object(), "sample_rate": 16000}
        with patch.object(observations.shutil, "which", return_value="ffmpeg"), patch.object(
            observations, "_package_available", return_value=True
        ), patch.object(
            observations.subprocess, "run", return_value=types.SimpleNamespace(returncode=0)
        ), patch.object(
            observations, "_load_pcm_waveform", return_value=(waveform, 30.0)
        ), patch.object(
            observations, "_load_speaker_pipeline", return_value=pipeline
        ), patch.dict(
            os.environ, {"HUGGINGFACE_TOKEN": "test-token"}, clear=False
        ):
            result = observations.analyze_speakers("recording.webm", CONFIG)

        pipeline.assert_called_once_with(waveform)
        self.assertNotIn("audio", pipeline.call_args.args[0])
        self.assertEqual(result["status"], "insufficient_audio")

    def test_single_speaker(self):
        segments = [speaker_segment(0, 12, "SPEAKER_00"), speaker_segment(12.3, 29.5, "SPEAKER_00")]
        result = aggregate_diarization_segments(segments, 30.0, CONFIG)
        self.assertEqual(result["estimated_speaker_count"], 1)
        self.assertFalse(result["possible_additional_speaker"])

    def test_two_speakers_sequentially(self):
        segments = [speaker_segment(0, 22, "SPEAKER_00"), speaker_segment(22.2, 29.5, "SPEAKER_01")]
        result = aggregate_diarization_segments(segments, 30.0, CONFIG)
        self.assertEqual(result["estimated_speaker_count"], 2)
        self.assertTrue(result["possible_additional_speaker"])
        self.assertEqual(result["possible_second_speaker_intervals"][0]["speaker_label"], "SPEAKER_01")

    def test_two_speakers_overlapping(self):
        segments = [speaker_segment(0, 29.5, "SPEAKER_00"), speaker_segment(12.5, 17.5, "SPEAKER_01")]
        result = aggregate_diarization_segments(segments, 30.0, CONFIG)
        self.assertTrue(result["overlapping_speech_detected"])
        self.assertAlmostEqual(result["overlapping_speech_seconds"], 5.0, delta=0.1)

    def test_background_noise_without_speech_is_insufficient(self):
        result = aggregate_diarization_segments([], 5.0, CONFIG)
        self.assertEqual(result["status"], "insufficient_audio")
        self.assertFalse(result["candidate_speech_detected"])
        self.assertFalse(result["possible_additional_speaker"])

    def test_short_accidental_sound_is_ignored(self):
        segments = [
            speaker_segment(0, 3, "SPEAKER_00"),
            speaker_segment(3.1, 3.35, "SPEAKER_01"),
        ]
        result = aggregate_diarization_segments(segments, 4.0, CONFIG)
        self.assertEqual(result["estimated_speaker_count"], 1)
        self.assertFalse(result["possible_additional_speaker"])

    def test_short_overlapping_voice_is_not_reported_as_a_second_speaker(self):
        segments = [
            speaker_segment(0, 3, "SPEAKER_00"),
            speaker_segment(1.0, 1.6, "SPEAKER_01"),
        ]
        result = aggregate_diarization_segments(segments, 3.0, CONFIG)
        self.assertEqual(result["estimated_speaker_count"], 1)
        self.assertFalse(result["possible_additional_speaker"])
        self.assertFalse(result["overlapping_speech_detected"])

    def test_system_question_audio_is_explicitly_excluded(self):
        result = aggregate_diarization_segments([speaker_segment(0, 3, "SPEAKER_00")], 3.0, CONFIG)
        self.assertFalse(result["system_question_audio_included"])
        self.assertTrue(any("starts after question playback" in note for note in result["notes"]))

    def test_missing_hugging_face_token_is_explicit(self):
        with patch.object(observations.shutil, "which", return_value="ffmpeg"), patch.object(
            observations, "_package_available", return_value=True
        ), patch.dict(os.environ, {}, clear=True):
            result = observations.analyze_speakers("recording.webm", CONFIG)
        self.assertEqual(result["status"], "model_unavailable")
        self.assertIn("token is missing", result["status_reason"])

    def test_diarisation_model_load_failure_does_not_expose_token(self):
        with patch.object(observations.shutil, "which", return_value="ffmpeg"), patch.object(
            observations, "_package_available", return_value=True
        ), patch.object(
            observations.subprocess, "run", return_value=types.SimpleNamespace(returncode=0)
        ), patch.object(
            observations,
            "_load_pcm_waveform",
            return_value=({"waveform": "test", "sample_rate": 16000}, 3.0),
        ), patch.object(
            observations, "_load_speaker_pipeline", side_effect=RuntimeError("secret-test-token")
        ), patch.dict(
            os.environ, {"HUGGINGFACE_TOKEN": "secret-test-token"}, clear=False
        ):
            result = observations.analyze_speakers("recording.webm", CONFIG)
        self.assertEqual(result["status"], "model_unavailable")
        self.assertNotIn("secret-test-token", result["status_reason"])


class IsolationTests(unittest.TestCase):
    def test_optional_failure_preserves_transcript_score_and_playback(self):
        merge = load_merge_function()
        response = {
            "question_index": 0,
            "question": "Q",
            "transcript": "Answer",
            "video_url": "/video",
        }
        analysis = {
            "video_analysis_status": "completed",
            "video_observations": {"recording_quality": {"video_available": True}},
            "per_response_observations": [{
                "question_index": 0,
                "transcript": "Answer",
                "video_observations": {"filler_word_count": 0},
            }],
        }
        failure = unavailable_recording_observations("failed", "Optional analysis failed.")
        result = merge(analysis, [response], {0: failure})
        per_response = result["per_response_observations"][0]
        self.assertEqual(result["video_analysis_status"], "completed")
        self.assertEqual(per_response["transcript"], "Answer")
        self.assertEqual(per_response["video_observations"]["filler_word_count"], 0)
        self.assertEqual(per_response["video_observations"]["head_orientation"]["status"], "failed")
        self.assertEqual(response["video_url"], "/video")

    def test_completed_head_analysis_populates_deterministic_visibility(self):
        merge = load_merge_function()
        response = {"question_index": 0, "question": "Q", "transcript": "Answer"}
        analysis = {
            "video_analysis_status": "failed",
            "video_observations": {"recording_quality": {}},
            "per_response_observations": [],
        }
        recording = unavailable_recording_observations("failed", "unused")
        recording["head_orientation"].update(
            status="completed",
            sampled_frame_count=20,
            valid_face_frame_count=15,
            multiple_faces_detected=False,
        )

        result = merge(analysis, [response], {0: recording})
        quality = result["video_observations"]["recording_quality"]
        per_response = result["per_response_observations"][0]["video_observations"]
        self.assertEqual(quality["face_visible_percentage"], 75.0)
        self.assertFalse(quality["multiple_faces_detected"])
        self.assertEqual(per_response["face_visible_percentage"], 75.0)

    def test_timestamped_head_and_speaker_intervals_are_retained(self):
        merge = load_merge_function()
        response = {"question_index": 0, "question": "Q", "transcript": "Answer"}
        analysis = {
            "video_analysis_status": "completed",
            "video_observations": {"recording_quality": {}},
            "per_response_observations": [],
        }
        recording = unavailable_recording_observations("failed", "unused")
        head_intervals = [
            {"type": "sustained_downward_orientation", "start_seconds": 4.0, "end_seconds": 7.0},
            {"type": "face_absent", "start_seconds": 12.0, "end_seconds": 15.0},
        ]
        yaw_events = [
            {"movement_type": "yaw", "timestamp_seconds": 9.5, "magnitude_degrees": 34.0}
        ]
        additional_speaker_intervals = [
            {"speaker_label": "SPEAKER_01", "start_seconds": 18.0, "end_seconds": 23.0}
        ]
        overlap_intervals = [
            {"start_seconds": 20.0, "end_seconds": 22.0}
        ]
        recording["head_orientation"].update(
            status="completed",
            head_observation_intervals=head_intervals,
            rapid_movement_events=yaw_events,
        )
        recording["speaker_observations"].update(
            status="completed",
            possible_additional_speaker=True,
            possible_second_speaker_intervals=additional_speaker_intervals,
            overlapping_speech_detected=True,
            overlapping_speech_intervals=overlap_intervals,
        )

        result = merge(analysis, [response], {0: recording})
        per_response = result["per_response_observations"][0]["video_observations"]

        self.assertEqual(per_response["head_orientation"]["head_observation_intervals"], head_intervals)
        self.assertEqual(per_response["head_orientation"]["rapid_movement_events"], yaw_events)
        self.assertEqual(
            per_response["speaker_observations"]["possible_second_speaker_intervals"],
            additional_speaker_intervals,
        )
        self.assertEqual(
            per_response["speaker_observations"]["overlapping_speech_intervals"],
            overlap_intervals,
        )

    def test_observations_do_not_modify_scores(self):
        merge = load_merge_function()
        assessment = {"overall_interview_score": 83, "answer_assessments": [{"score": 83}]}
        original = copy.deepcopy(assessment)
        analysis = {"video_analysis_status": "completed", "video_observations": {}, "per_response_observations": []}
        merge(analysis, [], {})
        self.assertEqual(assessment, original)
        self.assertNotIn("overall_interview_score", analysis)

    def test_manual_aggregate_script_exists(self):
        self.assertTrue(Path(__file__).with_name("analyze_recording.py").is_file())


if __name__ == "__main__":
    unittest.main()
