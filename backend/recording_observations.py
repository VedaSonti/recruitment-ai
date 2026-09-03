"""Neutral, score-independent observations from recorded interview responses.

Face landmarks and acoustic feature vectors exist only while this module is running.
Only the aggregate dictionaries returned by the public functions are persisted.
"""

from __future__ import annotations

import importlib
import importlib.util
import math
import os
import shutil
import subprocess
import tempfile
import threading
import time
import wave
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

import numpy as np


OBSERVATION_SCHEMA_VERSION = 3
BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_DIR.parent


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class ObservationConfig:
    head_sample_fps: float = _env_float(
        "HEAD_SAMPLE_FPS", _env_float("HEAD_POSE_SAMPLE_FPS", 2.0)
    )
    head_down_pitch_threshold_degrees: float = _env_float(
        "HEAD_DOWN_PITCH_THRESHOLD_DEGREES", 18.0
    )
    head_down_min_duration_seconds: float = _env_float(
        "HEAD_DOWN_MIN_DURATION_SECONDS", 2.0
    )
    head_movement_delta_threshold_degrees: float = _env_float(
        "HEAD_RAPID_DELTA_THRESHOLD_DEGREES",
        _env_float("HEAD_MOVEMENT_DELTA_THRESHOLD_DEGREES", 40.0),
    )
    head_movement_window_seconds: float = _env_float(
        "HEAD_RAPID_WINDOW_SECONDS",
        _env_float("HEAD_MOVEMENT_WINDOW_SECONDS", 0.75),
    )
    face_absent_min_duration_seconds: float = _env_float(
        "FACE_ABSENT_MIN_DURATION_SECONDS", 2.0
    )
    min_valid_face_frames: int = _env_int("MIN_VALID_FACE_FRAMES", 5)
    min_face_coverage_percent: float = _env_float("MIN_FACE_COVERAGE_PERCENT", 30.0)
    toward_screen_yaw_degrees: float = _env_float("TOWARD_SCREEN_YAW_DEGREES", 35.0)
    toward_screen_pitch_degrees: float = _env_float("TOWARD_SCREEN_PITCH_DEGREES", 22.0)
    min_secondary_speaker_seconds: float = _env_float(
        "MIN_SECONDARY_SPEAKER_SECONDS", 1.5
    )
    min_speaker_segment_seconds: float = _env_float(
        "MIN_SPEAKER_SEGMENT_SECONDS", 0.5
    )
    min_total_speech_seconds: float = _env_float("MIN_TOTAL_SPEECH_SECONDS", 2.0)
    speaker_confidence_threshold: float = _env_float(
        "SPEAKER_CONFIDENCE_THRESHOLD", 0.65
    )


DEFAULT_CONFIG = ObservationConfig()


def _configured_path(name: str, default: Path) -> Path:
    configured = Path(os.getenv(name, str(default)))
    if not configured.is_absolute():
        configured = PROJECT_ROOT / configured
    return configured.resolve()


def face_landmarker_model_path() -> Path:
    return _configured_path(
        "FACE_LANDMARKER_MODEL_PATH",
        BACKEND_DIR / "models" / "mediapipe" / "face_landmarker.task",
    )


def _resolve_ffmpeg_executable() -> Optional[str]:
    """Prefer local PATH FFmpeg, then the packaged serverless-safe binary."""
    path_executable = shutil.which("ffmpeg")
    if path_executable:
        return path_executable
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError, OSError, RuntimeError, ValueError):
        return None


def _package_available(name: str, verify_import: bool = False) -> bool:
    try:
        if verify_import:
            importlib.import_module(name)
            return True
        return importlib.util.find_spec(name) is not None
    except Exception as package_error:
        print(
            "[recording observations] Package import failed "
            f"package={name} error_type={type(package_error).__name__}"
        )
        return False


def recording_analysis_startup_status() -> dict:
    """Verify package imports and configuration without loading model weights."""
    face_package = _package_available("mediapipe", verify_import=True)
    face_model = face_landmarker_model_path().is_file()
    speaker_package = _package_available("pyannote.audio")
    speaker_token = bool(os.getenv("HUGGINGFACE_TOKEN", "").strip())
    return {
        "face_landmarker_package": "available" if face_package else "missing_package",
        "face_landmarker_model": "available" if face_model else "missing_model",
        "speaker_diarization_package": "available" if speaker_package else "missing_package",
        "speaker_diarization_token": "configured" if speaker_token else "missing_token",
        "speaker_diarization_model": os.getenv(
            "SPEAKER_DIARIZATION_MODEL", "pyannote/speaker-diarization-community-1"
        ),
    }


def _round(value: Optional[float], digits: int = 1) -> Optional[float]:
    return None if value is None else round(float(value), digits)


def _longest_boolean_interval(
    samples: list[dict], predicate, default_step: float
) -> tuple[float, Optional[float], Optional[float]]:
    longest = 0.0
    longest_start = None
    longest_end = None
    run_start = None
    previous_time = None
    for sample in samples:
        timestamp = float(sample["time_seconds"])
        if predicate(sample):
            if run_start is None or (
                previous_time is not None
                and timestamp - previous_time > default_step * 1.75
            ):
                run_start = timestamp
            duration = timestamp - run_start + default_step
            if duration > longest:
                longest = duration
                longest_start = run_start
                longest_end = timestamp + default_step
        else:
            run_start = None
        previous_time = timestamp
    return longest, longest_start, longest_end


def aggregate_head_pose_samples(
    samples: Iterable[dict], config: ObservationConfig = DEFAULT_CONFIG
) -> dict:
    ordered = sorted(list(samples), key=lambda item: float(item.get("time_seconds", 0)))
    sampled_count = len(ordered)
    clear_face = [item for item in ordered if item.get("face_count") == 1 and all(
        isinstance(item.get(axis), (int, float)) for axis in ("pitch", "yaw", "roll")
    )]
    multiple_face_frames = sum(1 for item in ordered if (item.get("face_count") or 0) > 1)
    valid_count = len(clear_face)
    coverage = (valid_count / sampled_count * 100.0) if sampled_count else 0.0
    step = 1.0 / max(config.head_sample_fps, 0.1)
    if len(ordered) > 1:
        deltas = [
            float(ordered[index]["time_seconds"]) - float(ordered[index - 1]["time_seconds"])
            for index in range(1, len(ordered))
            if float(ordered[index]["time_seconds"]) > float(ordered[index - 1]["time_seconds"])
        ]
        if deltas:
            step = float(np.median(deltas))
    absent = lambda item: int(item.get("face_count") or 0) == 0
    absent_count = sum(1 for item in ordered if absent(item))
    absent_longest, absent_start, absent_end = _longest_boolean_interval(ordered, absent, step)
    absent_interval = (
        {"start_seconds": _round(absent_start), "end_seconds": _round(absent_end)}
        if absent_start is not None else None
    )
    base = {
        "status": "completed",
        "status_reason": "Head analysis completed.",
        "candidate_visible": "true" if valid_count else "false" if sampled_count else "unknown",
        "sampled_frame_count": sampled_count,
        "valid_face_frame_count": valid_count,
        "face_detection_coverage_percent": _round(coverage),
        "multiple_faces_detected": multiple_face_frames > 0 if sampled_count else None,
        "face_absent_frame_count": absent_count,
        "face_absent_percent": _round(absent_count / sampled_count * 100) if sampled_count else None,
        "longest_face_absent_interval_seconds": _round(absent_longest) if sampled_count else None,
        "longest_face_absent_interval": absent_interval,
        "candidate_left_frame": absent_longest >= config.face_absent_min_duration_seconds,
        "downward_frame_count": 0,
        "downward_percent_of_valid_frames": None,
        "longest_downward_interval_seconds": None,
        "longest_downward_interval": None,
        "sustained_downward_observed": False,
        "rapid_movement_count": 0,
        "rapid_movement_events": [],
        "head_observation_intervals": ([
            {
                "start_seconds": _round(absent_start),
                "end_seconds": _round(absent_end),
                "type": "face_absent",
            }
        ] if absent_longest >= config.face_absent_min_duration_seconds and absent_start is not None else []),
        "mainly_toward_screen": "unknown",
        "notes": [],
    }
    if sampled_count == 0:
        base.update(status="insufficient_frames", status_reason="No sampled video frames were available for head-orientation analysis.")
        return base
    if valid_count < config.min_valid_face_frames or coverage < config.min_face_coverage_percent:
        base.update(
            status="insufficient_frames",
            status_reason="Insufficient clear face frames for head-orientation analysis.",
            notes=["Camera position, lighting, glasses, or partial face visibility can reduce measurement coverage."],
        )
        return base

    downward = lambda item: float(item["pitch"]) >= config.head_down_pitch_threshold_degrees
    downward_count = sum(1 for item in clear_face if downward(item))
    longest, interval_start, interval_end = _longest_boolean_interval(clear_face, downward, step)
    rapid_events = []
    previous = clear_face[0]
    last_event_time = -math.inf
    for current in clear_face[1:]:
        elapsed = float(current["time_seconds"]) - float(previous["time_seconds"])
        if 0 < elapsed <= config.head_movement_window_seconds:
            changes = {
                axis: abs(float(current[axis]) - float(previous[axis]))
                for axis in ("pitch", "yaw", "roll")
            }
            movement_type, delta = max(changes.items(), key=lambda item: item[1])
            timestamp = float(current["time_seconds"])
            if (
                delta >= config.head_movement_delta_threshold_degrees
                and timestamp - last_event_time >= config.head_movement_window_seconds
            ):
                rapid_events.append({
                    "time_seconds": _round(timestamp),
                    "movement_type": movement_type,
                    "delta_degrees": _round(delta),
                })
                last_event_time = timestamp
        previous = current

    toward_count = sum(
        1 for item in clear_face
        if abs(float(item["yaw"])) <= config.toward_screen_yaw_degrees
        and abs(float(item["pitch"])) <= config.toward_screen_pitch_degrees
    )
    toward_ratio = toward_count / valid_count
    mainly_toward = "yes" if toward_ratio >= 0.8 else "no" if toward_ratio < 0.4 else "mixed"
    observation_intervals = []
    if longest >= config.head_down_min_duration_seconds and interval_start is not None:
        observation_intervals.append({
            "start_seconds": _round(interval_start),
            "end_seconds": _round(interval_end),
            "type": "sustained_downward_orientation",
        })
    if absent_longest >= config.face_absent_min_duration_seconds and absent_start is not None:
        observation_intervals.append({
            "start_seconds": _round(absent_start),
            "end_seconds": _round(absent_end),
            "type": "face_absent",
        })
    base.update(
        downward_frame_count=downward_count,
        downward_percent_of_valid_frames=_round(downward_count / valid_count * 100),
        longest_downward_interval_seconds=_round(longest),
        longest_downward_interval=(
            {"start_seconds": _round(interval_start), "end_seconds": _round(interval_end)}
            if interval_start is not None else None
        ),
        sustained_downward_observed=longest >= config.head_down_min_duration_seconds,
        rapid_movement_count=len(rapid_events),
        rapid_movement_events=rapid_events,
        head_observation_intervals=observation_intervals,
        mainly_toward_screen=mainly_toward,
        notes=[
            "Head orientation is a geometric estimate, not a measure of attention or intent.",
            "Brief movements are excluded; camera placement and looking at the question, keyboard, notes, or another screen can affect the measurement.",
        ],
    )
    return base


def _rotation_angles(rotation_vector: np.ndarray) -> tuple[float, float, float]:
    import cv2

    matrix, _ = cv2.Rodrigues(rotation_vector)
    projection = np.hstack((matrix, np.zeros((3, 1), dtype=np.float64)))
    angles = cv2.decomposeProjectionMatrix(projection)[6].flatten()
    pitch, yaw, roll = (_normalize_pose_angle(float(value)) for value in angles[:3])
    # OpenCV's generic model has downward pitch as negative on common webcams.
    return -pitch, yaw, roll


def _normalize_pose_angle(value: float) -> float:
    """Collapse equivalent Euler representations into a visible +/-90° range."""
    normalized = (value + 180.0) % 360.0 - 180.0
    if normalized > 90.0:
        normalized = 180.0 - normalized
    elif normalized < -90.0:
        normalized = -180.0 - normalized
    return normalized


def _create_face_landmarker(mp, model_path: Path):
    vision = mp.tasks.vision
    options = vision.FaceLandmarkerOptions(
        base_options=mp.tasks.BaseOptions(model_asset_path=str(model_path)),
        running_mode=vision.RunningMode.VIDEO,
        num_faces=2,
        min_face_detection_confidence=0.55,
        min_face_presence_confidence=0.55,
        min_tracking_confidence=0.55,
        output_face_blendshapes=False,
        output_facial_transformation_matrixes=True,
    )
    return vision, vision.FaceLandmarker.create_from_options(options)


def analyze_head_pose(
    video_path: str, config: ObservationConfig = DEFAULT_CONFIG
) -> dict:
    started = time.monotonic()
    try:
        import cv2
        import mediapipe as mp
    except Exception as import_error:
        print(f"[head analysis] MediaPipe import failed error_type={type(import_error).__name__}")
        return {
            **aggregate_head_pose_samples([], config),
            "status": "model_unavailable",
            "status_reason": "The MediaPipe package is missing or could not be imported in the backend environment.",
            "analysis_duration_seconds": _round(time.monotonic() - started, 2),
        }

    model_path = face_landmarker_model_path()
    if not model_path.is_file():
        return {
            **aggregate_head_pose_samples([], config),
            "status": "model_unavailable",
            "status_reason": "The Face Landmarker model is not installed at the configured path.",
            "analysis_duration_seconds": _round(time.monotonic() - started, 2),
        }
    try:
        vision = mp.tasks.vision
        # Validate the Tasks API before opening the recording.
        vision.FaceLandmarkerOptions
        mp.tasks.BaseOptions
    except (AttributeError, TypeError, ValueError, RuntimeError) as model_error:
        print(f"[head analysis] Face Landmarker configuration failed error_type={type(model_error).__name__}")
        return {
            **aggregate_head_pose_samples([], config),
            "status": "model_unavailable",
            "status_reason": "The installed MediaPipe package does not provide a usable Face Landmarker Tasks API.",
            "analysis_duration_seconds": _round(time.monotonic() - started, 2),
        }

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return {
            **aggregate_head_pose_samples([], config),
            "status": "failed",
            "status_reason": "Video recorded, but head-orientation frame analysis failed.",
            "analysis_duration_seconds": _round(time.monotonic() - started, 2),
        }
    samples = []
    sample_interval = 1.0 / max(config.head_sample_fps, 0.1)
    object_points = np.array([
        (0.0, 0.0, 0.0), (0.0, -330.0, -65.0),
        (-225.0, 170.0, -135.0), (225.0, 170.0, -135.0),
        (-150.0, -150.0, -125.0), (150.0, -150.0, -125.0),
    ], dtype=np.float64)
    landmark_indexes = (1, 152, 33, 263, 61, 291)
    try:
        vision, face_landmarker = _create_face_landmarker(mp, model_path)
    except Exception as model_error:
        cap.release()
        print(f"[head analysis] Face Landmarker model load failed error_type={type(model_error).__name__}")
        return {
            **aggregate_head_pose_samples([], config),
            "status": "model_unavailable",
            "status_reason": "The configured Face Landmarker model could not be loaded.",
            "analysis_duration_seconds": _round(time.monotonic() - started, 2),
        }
    try:
        with face_landmarker:
            frame_index = 0
            next_sample_time = 0.0
            last_timestamp_ms = -1
            while True:
                ok, frame = cap.read()
                if not ok:
                    break
                decoded_time = float(cap.get(cv2.CAP_PROP_POS_MSEC) or 0) / 1000.0
                # Some decoders omit timestamps. A conservative 30 fps fallback
                # prevents analysing every frame while keeping the output usable.
                timestamp = decoded_time if decoded_time > 0 or frame_index == 0 else frame_index / 30.0
                if timestamp + 1e-6 < next_sample_time:
                    frame_index += 1
                    continue
                next_sample_time = timestamp + sample_interval
                height, width = frame.shape[:2]
                rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                timestamp_ms = max(last_timestamp_ms + 1, int(round(timestamp * 1000)))
                last_timestamp_ms = timestamp_ms
                media_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)
                result = face_landmarker.detect_for_video(media_image, timestamp_ms)
                faces = result.face_landmarks or []
                sample = {"time_seconds": timestamp, "face_count": len(faces)}
                if len(faces) == 1:
                    points = np.array([
                        (faces[0][index].x * width, faces[0][index].y * height)
                        for index in landmark_indexes
                    ], dtype=np.float64)
                    focal = float(width)
                    camera = np.array([
                        [focal, 0, width / 2], [0, focal, height / 2], [0, 0, 1]
                    ], dtype=np.float64)
                    success, rotation, _ = cv2.solvePnP(
                        object_points, points, camera, np.zeros((4, 1)), flags=cv2.SOLVEPNP_ITERATIVE
                    )
                    if success:
                        pitch, yaw, roll = _rotation_angles(rotation)
                        sample.update(pitch=pitch, yaw=yaw, roll=roll)
                samples.append(sample)
                frame_index += 1
    except Exception as analysis_error:
        print(f"[head analysis] Face Landmarker run failed error_type={type(analysis_error).__name__}")
        result = aggregate_head_pose_samples(samples, config)
        result.update(status="failed", status_reason="The Face Landmarker model could not analyse this recording.")
    else:
        result = aggregate_head_pose_samples(samples, config)
    finally:
        cap.release()
    result["analysis_duration_seconds"] = _round(time.monotonic() - started, 2)
    return result


def _merge_intervals(intervals: Iterable[dict], max_gap: float = 0.15) -> list[dict]:
    ordered = sorted(
        (
            {"start_seconds": float(item["start_seconds"]), "end_seconds": float(item["end_seconds"])}
            for item in intervals
            if float(item.get("end_seconds", 0)) > float(item.get("start_seconds", 0))
        ),
        key=lambda item: item["start_seconds"],
    )
    merged = []
    for item in ordered:
        if merged and item["start_seconds"] <= merged[-1]["end_seconds"] + max_gap:
            merged[-1]["end_seconds"] = max(merged[-1]["end_seconds"], item["end_seconds"])
        else:
            merged.append(dict(item))
    return merged


def _interval_duration(intervals: Iterable[dict]) -> float:
    return sum(item["end_seconds"] - item["start_seconds"] for item in _merge_intervals(intervals))


def aggregate_diarization_segments(
    segments: Iterable[dict],
    duration_seconds: float,
    config: ObservationConfig = DEFAULT_CONFIG,
) -> dict:
    ordered = sorted(
        (
            {
                "start_seconds": float(item["start_seconds"]),
                "end_seconds": float(item["end_seconds"]),
                "speaker_label": str(item.get("speaker_label") or "SPEAKER_UNKNOWN"),
            }
            for item in segments
            if float(item.get("end_seconds", 0)) - float(item.get("start_seconds", 0))
            >= config.min_speaker_segment_seconds
        ),
        key=lambda item: (item["start_seconds"], item["end_seconds"]),
    )
    base = {
        "status": "completed",
        "status_reason": "Speaker diarisation completed.",
        "analysis_method": "pyannote_speaker_diarization",
        "candidate_speech_detected": False,
        "estimated_speaker_count": None,
        "possible_additional_speaker": False,
        "overlapping_speech_detected": False,
        "overlapping_speech_seconds": 0.0,
        "possible_second_speaker_intervals": [],
        "overlapping_speech_intervals": [],
        "speaker_analysis_confidence": 0.0,
        "speaker_confidence_label": "low",
        "system_question_audio_included": False,
        "notes": [
            "Diarisation distinguishes acoustically different speech segments; it does not identify a person.",
            "The recording starts after question playback, so the system-generated question voice is excluded.",
        ],
    }
    speech_seconds = _interval_duration(ordered)
    if duration_seconds <= 0 or speech_seconds < config.min_total_speech_seconds:
        base.update(
            status="insufficient_audio",
            status_reason="Audio quality or speech duration was insufficient for speaker diarisation.",
            estimated_speaker_count=0 if not ordered else None,
        )
        return base

    by_speaker: dict[str, list[dict]] = {}
    for item in ordered:
        by_speaker.setdefault(item["speaker_label"], []).append(item)
    totals = {
        label: sum(item["end_seconds"] - item["start_seconds"] for item in items)
        for label, items in by_speaker.items()
    }
    primary_label = max(totals, key=totals.get)
    secondary_labels = [
        label for label, total in totals.items()
        if label != primary_label and total >= config.min_secondary_speaker_seconds
    ]
    secondary_seconds = sum(totals[label] for label in secondary_labels)
    secondary_segment_count = sum(len(by_speaker[label]) for label in secondary_labels)
    additional_confidence = min(
        0.95,
        0.55
        + 0.2 * min(1.0, secondary_seconds / max(config.min_secondary_speaker_seconds, 0.1))
        + 0.1 * min(1.0, secondary_segment_count / 3),
    ) if secondary_labels else 0.75
    possible_additional = bool(
        secondary_labels and additional_confidence >= config.speaker_confidence_threshold
    )

    additional_intervals = []
    if possible_additional:
        for label in secondary_labels:
            for interval in _merge_intervals(by_speaker[label]):
                additional_intervals.append({
                    "start_seconds": _round(interval["start_seconds"]),
                    "end_seconds": _round(interval["end_seconds"]),
                    "speaker_label": label,
                })

    overlap_speakers = {primary_label, *secondary_labels} if possible_additional else {primary_label}
    overlap_candidates = [
        item for item in ordered if item["speaker_label"] in overlap_speakers
    ]
    overlaps = []
    for index, first in enumerate(overlap_candidates):
        for second in overlap_candidates[index + 1:]:
            if second["start_seconds"] >= first["end_seconds"]:
                break
            if first["speaker_label"] == second["speaker_label"]:
                continue
            start = max(first["start_seconds"], second["start_seconds"])
            end = min(first["end_seconds"], second["end_seconds"])
            if end > start:
                overlaps.append({"start_seconds": start, "end_seconds": end})
    merged_overlaps = _merge_intervals(overlaps, max_gap=0.05)
    overlap_seconds = sum(item["end_seconds"] - item["start_seconds"] for item in merged_overlaps)
    confidence_label = "high" if additional_confidence >= 0.8 else "moderate" if additional_confidence >= 0.65 else "low"
    base.update(
        candidate_speech_detected=True,
        estimated_speaker_count=1 + len(secondary_labels),
        possible_additional_speaker=possible_additional,
        overlapping_speech_detected=overlap_seconds > 0,
        overlapping_speech_seconds=_round(overlap_seconds),
        possible_second_speaker_intervals=sorted(additional_intervals, key=lambda item: item["start_seconds"]),
        overlapping_speech_intervals=[
            {"start_seconds": _round(item["start_seconds"]), "end_seconds": _round(item["end_seconds"])}
            for item in merged_overlaps
        ],
        speaker_analysis_confidence=_round(additional_confidence, 2),
        speaker_confidence_label=confidence_label,
    )
    return base


# Backward-compatible helper name retained for existing stored-observation tests.
aggregate_speaker_segments = aggregate_diarization_segments


_speaker_pipeline = None
_speaker_pipeline_model = None
_speaker_pipeline_lock = threading.Lock()
_speaker_pipeline_load_timing = {
    "speaker_model_download_seconds": 0.0,
    "speaker_model_initialization_seconds": 0.0,
    "speaker_model_cache_hit": False,
}
_torchcodec_status_reported = False


def _import_speaker_pipeline_class():
    """Import pyannote while containing its optional decoder warning only."""
    global _torchcodec_status_reported
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=r"\ntorchcodec is not installed correctly so built-in audio decoding will fail\..*",
            category=UserWarning,
            module=r"pyannote\.audio\.core\.io",
        )
        from pyannote.audio import Pipeline
        from pyannote.audio.core import io as pyannote_audio_io

    if (
        not getattr(pyannote_audio_io, "TORCHCODEC_AVAILABLE", False)
        and not _torchcodec_status_reported
    ):
        print(
            "[speaker analysis] TorchCodec unavailable; "
            "using the configured in-memory waveform input."
        )
        _torchcodec_status_reported = True
    return Pipeline


def _validate_speaker_minimum_samples(pipeline) -> int | None:
    """Run pyannote's one-time minimum-length probe under its exact known warning."""
    embedding = getattr(pipeline, "_embedding", None)
    if embedding is None:
        return None
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=r"std\(\): degrees of freedom is <= 0\..*",
            category=UserWarning,
            module=r"pyannote\.audio\.models\.blocks\.pooling",
        )
        minimum_samples = getattr(embedding, "min_num_samples", None)
    if minimum_samples is not None and int(minimum_samples) <= 0:
        raise RuntimeError("speaker embedding minimum sample length is invalid")
    return int(minimum_samples) if minimum_samples is not None else None


def _load_speaker_pipeline():
    global _speaker_pipeline, _speaker_pipeline_model, _speaker_pipeline_load_timing
    token = os.getenv("HUGGINGFACE_TOKEN", "").strip()
    model_name = os.getenv(
        "SPEAKER_DIARIZATION_MODEL", "pyannote/speaker-diarization-community-1"
    ).strip()
    if _speaker_pipeline is not None and _speaker_pipeline_model == model_name:
        _speaker_pipeline_load_timing = {
            "speaker_model_download_seconds": 0.0,
            "speaker_model_initialization_seconds": 0.0,
            "speaker_model_cache_hit": True,
        }
        print("[speaker analysis timing] model_cache_hit=true")
        return _speaker_pipeline

    with _speaker_pipeline_lock:
        if _speaker_pipeline is None or _speaker_pipeline_model != model_name:
            Pipeline = _import_speaker_pipeline_class()
            packaged_model = os.getenv("SPEAKER_DIARIZATION_MODEL_PATH", "").strip()
            download_started = time.monotonic()
            if packaged_model:
                checkpoint = Path(packaged_model)
                if not checkpoint.is_dir():
                    raise RuntimeError("Configured speaker diarisation model path is unavailable")
                download_seconds = 0.0
            else:
                from huggingface_hub import snapshot_download

                checkpoint = Path(snapshot_download(repo_id=model_name, token=token))
                download_seconds = time.monotonic() - download_started
            print(
                "[speaker analysis timing] "
                f"model_download_seconds={download_seconds:.3f} "
                f"model_source={'packaged' if packaged_model else 'huggingface'}"
            )
            initialization_started = time.monotonic()
            pipeline = Pipeline.from_pretrained(checkpoint, token=token)
            initialization_seconds = time.monotonic() - initialization_started
            print(
                "[speaker analysis timing] "
                f"model_initialization_seconds={initialization_seconds:.3f}"
            )
            if pipeline is None:
                raise RuntimeError("speaker pipeline was not loaded")
            device_name = os.getenv("SPEAKER_DIARIZATION_DEVICE", "cpu").strip().lower()
            if device_name == "cuda":
                import torch
                if not torch.cuda.is_available():
                    raise RuntimeError("CUDA was requested but is unavailable")
                pipeline.to(torch.device("cuda"))
            _validate_speaker_minimum_samples(pipeline)
            _speaker_pipeline = pipeline
            _speaker_pipeline_model = model_name
            _speaker_pipeline_load_timing = {
                "speaker_model_download_seconds": download_seconds,
                "speaker_model_initialization_seconds": initialization_seconds,
                "speaker_model_cache_hit": False,
            }
            print("[speaker analysis timing] model_cache_hit=false")
        else:
            _speaker_pipeline_load_timing = {
                "speaker_model_download_seconds": 0.0,
                "speaker_model_initialization_seconds": 0.0,
                "speaker_model_cache_hit": True,
            }
            print("[speaker analysis timing] model_cache_hit=true")
    return _speaker_pipeline


def _diarization_segments(output) -> list[dict]:
    annotation = getattr(output, "speaker_diarization", output)
    segments = []
    if hasattr(annotation, "itertracks"):
        for segment, _, speaker in annotation.itertracks(yield_label=True):
            segments.append({
                "start_seconds": float(segment.start),
                "end_seconds": float(segment.end),
                "speaker_label": str(speaker),
            })
        return segments
    for item in annotation:
        if len(item) == 2:
            segment, speaker = item
        else:
            segment, _, speaker = item
        segments.append({
            "start_seconds": float(segment.start),
            "end_seconds": float(segment.end),
            "speaker_label": str(speaker),
        })
    return segments


def _load_pcm_waveform(audio_path: str) -> tuple[dict, float]:
    """Load the FFmpeg-normalized WAV without relying on TorchCodec."""
    import torch

    with wave.open(audio_path, "rb") as source:
        sample_rate = source.getframerate()
        frame_count = source.getnframes()
        if source.getnchannels() != 1 or source.getsampwidth() != 2:
            raise ValueError("Expected mono 16-bit PCM audio")
        samples = np.frombuffer(source.readframes(frame_count), dtype="<i2")
    waveform = torch.from_numpy(samples.astype(np.float32) / 32768.0).unsqueeze(0)
    duration = frame_count / sample_rate if sample_rate else 0.0
    return {"waveform": waveform, "sample_rate": sample_rate}, duration


def analyze_speakers(
    video_path: str, config: ObservationConfig = DEFAULT_CONFIG
) -> dict:
    started = time.monotonic()
    timing = {
        "ffmpeg_seconds": 0.0,
        "speaker_model_load_seconds": 0.0,
        "speaker_model_download_seconds": 0.0,
        "speaker_model_initialization_seconds": 0.0,
        "speaker_inference_seconds": 0.0,
    }

    def finish(result: dict) -> dict:
        result["analysis_duration_seconds"] = _round(time.monotonic() - started, 2)
        result["_timing"] = {
            name: round(seconds, 3) for name, seconds in timing.items()
        }
        return result

    ffmpeg = _resolve_ffmpeg_executable()
    if not ffmpeg:
        result = aggregate_diarization_segments([], 0, config)
        result.update(status="model_unavailable", status_reason="FFmpeg is unavailable for diarisation audio extraction.")
        return finish(result)
    if not _package_available("pyannote.audio"):
        result = aggregate_diarization_segments([], 0, config)
        result.update(status="model_unavailable", status_reason="The pyannote.audio package is not installed in the backend environment.")
        return finish(result)
    if not os.getenv("HUGGINGFACE_TOKEN", "").strip():
        result = aggregate_diarization_segments([], 0, config)
        result.update(status="model_unavailable", status_reason="Speaker diarisation is not configured because the backend Hugging Face token is missing.")
        return finish(result)

    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as temporary:
            temporary_path = temporary.name
        ffmpeg_started = time.monotonic()
        completed = subprocess.run(
            [ffmpeg, "-v", "error", "-y", "-i", video_path, "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", temporary_path],
            capture_output=True,
            timeout=45,
            check=False,
        )
        if completed.returncode != 0:
            timing["ffmpeg_seconds"] = time.monotonic() - ffmpeg_started
            result = aggregate_diarization_segments([], 0, config)
            result.update(status="failed", status_reason="Audio could not be extracted for speaker diarisation.")
        else:
            waveform_input, duration = _load_pcm_waveform(temporary_path)
            timing["ffmpeg_seconds"] = time.monotonic() - ffmpeg_started
            if duration < config.min_total_speech_seconds:
                result = aggregate_diarization_segments([], duration, config)
                result.update(
                    status="insufficient_audio",
                    status_reason="The recording is too short to satisfy the minimum speech-duration rule.",
                )
            else:
                try:
                    model_load_started = time.monotonic()
                    pipeline = _load_speaker_pipeline()
                    timing["speaker_model_load_seconds"] = (
                        time.monotonic() - model_load_started
                    )
                    timing.update({
                        name: float(_speaker_pipeline_load_timing.get(name, 0.0) or 0.0)
                        for name in (
                            "speaker_model_download_seconds",
                            "speaker_model_initialization_seconds",
                        )
                    })
                except Exception as model_error:
                    print(f"[speaker analysis] Diarisation model load failed error_type={type(model_error).__name__}")
                    result = aggregate_diarization_segments([], duration, config)
                    result.update(
                        status="model_unavailable",
                        status_reason="The configured speaker diarisation model could not be loaded. Confirm model access and backend configuration.",
                    )
                else:
                    try:
                        inference_started = time.monotonic()
                        with _speaker_pipeline_lock:
                            output = pipeline(waveform_input)
                        timing["speaker_inference_seconds"] = (
                            time.monotonic() - inference_started
                        )
                        result = aggregate_diarization_segments(
                            _diarization_segments(output), duration, config
                        )
                    except Exception as analysis_error:
                        timing["speaker_inference_seconds"] = (
                            time.monotonic() - inference_started
                        )
                        print(f"[speaker analysis] Diarisation failed error_type={type(analysis_error).__name__}")
                        result = aggregate_diarization_segments([], duration, config)
                        result.update(status="failed", status_reason="Speaker diarisation failed for this recording.")
    except Exception as audio_error:
        print(f"[speaker analysis] Audio preparation failed error_type={type(audio_error).__name__}")
        result = aggregate_diarization_segments([], 0, config)
        result.update(status="failed", status_reason="Speaker diarisation failed without affecting the recording or transcript.")
    finally:
        if temporary_path:
            Path(temporary_path).unlink(missing_ok=True)
    return finish(result)


def analyze_recording(video_path: str, config: ObservationConfig = DEFAULT_CONFIG) -> dict:
    started = time.monotonic()
    head_started = time.monotonic()
    head = analyze_head_pose(video_path, config)
    head_seconds = time.monotonic() - head_started
    speaker = analyze_speakers(video_path, config)
    speaker_timing = speaker.pop("_timing", {})
    return {
        "observation_schema_version": OBSERVATION_SCHEMA_VERSION,
        "head_orientation": head,
        "speaker_observations": speaker,
        "_timing": {
            "ffmpeg_seconds": speaker_timing.get("ffmpeg_seconds", 0.0),
            "head_analysis_seconds": round(head_seconds, 3),
            "speaker_model_load_seconds": speaker_timing.get(
                "speaker_model_load_seconds", 0.0
            ),
            "speaker_model_download_seconds": speaker_timing.get(
                "speaker_model_download_seconds", 0.0
            ),
            "speaker_model_initialization_seconds": speaker_timing.get(
                "speaker_model_initialization_seconds", 0.0
            ),
            "speaker_inference_seconds": speaker_timing.get(
                "speaker_inference_seconds", 0.0
            ),
            "analysis_total_seconds": round(time.monotonic() - started, 3),
        },
    }


def unavailable_recording_observations(status: str, reason: str) -> dict:
    """Return the same persisted shape when a recording cannot be analysed."""
    head = aggregate_head_pose_samples([])
    head.update(status=status, status_reason=reason)
    speaker = aggregate_speaker_segments([], 0)
    speaker.update(status=status, status_reason=reason)
    return {
        "observation_schema_version": OBSERVATION_SCHEMA_VERSION,
        "head_orientation": head,
        "speaker_observations": speaker,
    }
