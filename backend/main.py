"""
main.py
-------
FastAPI app exposing your matching pipeline as an API instead of a script
you run by hand. Reuses parse_jd / parse_cv / embedding logic you already
built and validated in match_core_v3.py — this file just wraps it in
endpoints and stores results in MongoDB instead of a local JSON file.

Setup (run once):
    pip install fastapi uvicorn motor pymongo python-multipart

Run the server:
    uvicorn main:app --reload

Then open in your browser:
    http://127.0.0.1:8000/docs
This gives you an interactive page to test every endpoint without Postman.
"""

import asyncio
import os
import re
import base64
import json
import hashlib
import tempfile
import io
from pathlib import Path, PurePosixPath
import secrets
import time
from datetime import datetime, timezone, timedelta
from typing import Optional
from bson import ObjectId

import numpy as np
from PIL import Image
from fastapi import Depends, FastAPI, UploadFile, File, HTTPException, Form
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pymongo.errors import DuplicateKeyError
from openai import OpenAI
from dotenv import load_dotenv

from prompts import (
    build_jd_parse_prompt,
    build_cv_parse_prompt,
    build_embedding_text_from_job,
    build_embedding_text_from_candidate,
)
from file_loader import load_text_file
from db import (
    jobs_collection,
    candidates_collection,
    matches_collection,
    generated_profiles_collection,
    interviews_collection,
    password_reset_tokens_collection,
    recruiter_users_collection,
)
from auth import get_current_recruiter, router as auth_router
from email_service import send_email
from profile_pdf import generate_profile_pdf
from recording_observations import (
    OBSERVATION_SCHEMA_VERSION,
    analyze_recording,
    recording_analysis_startup_status,
    unavailable_recording_observations,
)
from weaviate_service import (
    close_weaviate,
    connect_to_weaviate,
    ensure_collections as ensure_weaviate_collections,
    insert_candidate_vector,
    insert_job_vector,
    search_candidates as search_weaviate_candidates,
    search_jobs as search_weaviate_jobs,
)

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")
BACKEND_DIR = Path(__file__).resolve().parent
_configured_interview_media_root = Path(
    os.getenv("INTERVIEW_MEDIA_ROOT", str(BACKEND_DIR / "media" / "interviews"))
)
if not _configured_interview_media_root.is_absolute():
    _configured_interview_media_root = BACKEND_DIR / _configured_interview_media_root
INTERVIEW_MEDIA_ROOT = _configured_interview_media_root.resolve()
INTERVIEW_VIDEO_KEY_PREFIX = PurePosixPath("media/interviews")

_configured_profile_media_root = Path(
    os.getenv("PROFILE_MEDIA_ROOT", str(BACKEND_DIR / "media" / "profiles"))
)
if not _configured_profile_media_root.is_absolute():
    _configured_profile_media_root = BACKEND_DIR / _configured_profile_media_root
PROFILE_MEDIA_ROOT = _configured_profile_media_root.resolve()
PROFILE_FILE_KEY_PREFIX = PurePosixPath("media/profiles")

_configured_candidate_media_root = Path(
    os.getenv("CANDIDATE_MEDIA_ROOT", str(BACKEND_DIR / "media" / "candidates"))
)
if not _configured_candidate_media_root.is_absolute():
    _configured_candidate_media_root = BACKEND_DIR / _configured_candidate_media_root
CANDIDATE_MEDIA_ROOT = _configured_candidate_media_root.resolve()
CANDIDATE_FILE_KEY_PREFIX = PurePosixPath("media/candidates")

CHAT_MODEL = "gpt-4o-mini"
EMBED_MODEL = "text-embedding-3-small"
VECTOR_BACKEND = os.getenv("VECTOR_BACKEND", "mongodb").strip().lower()
if VECTOR_BACKEND not in {"mongodb", "weaviate"}:
    raise RuntimeError("VECTOR_BACKEND must be either 'mongodb' or 'weaviate'")

def interview_video_storage_key(interview_id, question_index: int) -> str:
    """Return the portable media key stored with an interview response."""
    if question_index < 0:
        raise HTTPException(400, "Invalid question index")

    safe_interview_id = re.sub(r"[^a-fA-F0-9]", "", str(interview_id))
    if not safe_interview_id or safe_interview_id != str(interview_id):
        raise HTTPException(400, "Invalid interview id")

    return str(
        INTERVIEW_VIDEO_KEY_PREFIX / safe_interview_id / f"{question_index}.webm"
    )


def resolve_interview_video_storage_key(storage_key: str) -> Optional[Path]:
    """Resolve a portable media key without allowing access outside the media root."""
    if not isinstance(storage_key, str) or not storage_key:
        return None

    try:
        key_path = PurePosixPath(storage_key)
    except (TypeError, ValueError):
        return None

    prefix_parts = INTERVIEW_VIDEO_KEY_PREFIX.parts
    if (
        key_path.is_absolute()
        or ".." in key_path.parts
        or key_path.parts[:len(prefix_parts)] != prefix_parts
        or len(key_path.parts) != len(prefix_parts) + 2
    ):
        return None

    interview_id, filename = key_path.parts[-2:]
    if not re.fullmatch(r"[a-fA-F0-9]+", interview_id):
        return None
    if not re.fullmatch(r"\d+\.webm", filename):
        return None

    try:
        media_root = INTERVIEW_MEDIA_ROOT.resolve()
        video_path = (media_root / interview_id / filename).resolve()
    except (OSError, RuntimeError):
        return None

    if media_root != video_path and media_root not in video_path.parents:
        return None

    return video_path


def resolve_stored_interview_video_path(response: dict) -> Optional[Path]:
    """Resolve a portable key, or a legacy path only when it is inside the media root."""
    video_path = resolve_interview_video_storage_key(
        response.get("video_storage_key")
    )
    if video_path:
        return video_path

    legacy_path = response.get("video_path")
    if not isinstance(legacy_path, str) or not legacy_path:
        return None

    try:
        media_root = INTERVIEW_MEDIA_ROOT.resolve()
        video_path = Path(legacy_path).resolve()
    except (OSError, RuntimeError):
        return None

    if media_root != video_path and media_root not in video_path.parents:
        return None

    return video_path


def _safe_media_path(root: Path, *parts: str) -> Optional[Path]:
    """Resolve a controlled media path without allowing traversal."""
    try:
        resolved_root = root.resolve()
        resolved_path = resolved_root.joinpath(*parts).resolve()
    except (OSError, RuntimeError, TypeError, ValueError):
        return None
    if resolved_root != resolved_path and resolved_root not in resolved_path.parents:
        return None
    return resolved_path


def profile_pdf_storage_key(match_id: ObjectId) -> str:
    return str(PROFILE_FILE_KEY_PREFIX / str(match_id) / "candidate-profile.pdf")


def resolve_profile_pdf_storage_key(storage_key: str) -> Optional[Path]:
    try:
        key = PurePosixPath(storage_key)
    except (TypeError, ValueError):
        return None
    if (
        key.is_absolute()
        or ".." in key.parts
        or key.parts[:2] != PROFILE_FILE_KEY_PREFIX.parts
        or len(key.parts) != 4
        or not ObjectId.is_valid(key.parts[2])
        or key.parts[3] != "candidate-profile.pdf"
    ):
        return None
    return _safe_media_path(PROFILE_MEDIA_ROOT, key.parts[2], key.parts[3])


def candidate_cv_storage_key(candidate_id: ObjectId, filename: str) -> str:
    suffix = Path(filename or "candidate.pdf").suffix.lower()
    if suffix not in {".pdf", ".docx"}:
        suffix = ".bin"
    return str(CANDIDATE_FILE_KEY_PREFIX / str(candidate_id) / f"original{suffix}")


def resolve_candidate_cv_storage_key(storage_key: str) -> Optional[Path]:
    try:
        key = PurePosixPath(storage_key)
    except (TypeError, ValueError):
        return None
    if (
        key.is_absolute()
        or ".." in key.parts
        or key.parts[:2] != CANDIDATE_FILE_KEY_PREFIX.parts
        or len(key.parts) != 4
        or not ObjectId.is_valid(key.parts[2])
        or not re.fullmatch(r"original\.(pdf|docx|bin)", key.parts[3])
    ):
        return None
    return _safe_media_path(CANDIDATE_MEDIA_ROOT, key.parts[2], key.parts[3])


def get_video_duration_seconds(video_path: str) -> Optional[float]:
    """Best-effort video duration from OpenCV metadata."""
    try:
        import cv2
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return None
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = cap.get(cv2.CAP_PROP_FPS) or 0
        cap.release()
        if total_frames <= 0 or fps <= 0:
            return None
        return round(total_frames / fps, 1)
    except Exception:
        return None


def response_has_video(response: dict) -> bool:
    return bool(
        response.get("video_url")
        or response.get("video_storage_key")
        # Legacy records may contain an absolute video_path whose temporary or
        # local file is no longer available. Treat it as upload evidence only.
        or response.get("video_path")
        or response.get("video_size_bytes")
        or response.get("video_content_type")
        or response.get("frames_b64")
    )


def response_video_playback(
    match_id: str,
    response: dict,
) -> tuple[Optional[str], str]:
    """Return a controlled playback URL and an explicit playback state."""
    storage_key = response.get("video_storage_key")
    if storage_key:
        video_path = resolve_stored_interview_video_path(response)
        if video_path and video_path.is_file():
            question_index = response.get("question_index")
            return (
                f"/interviews/by-match/{match_id}/responses/{question_index}/video",
                "available",
            )
        return None, "missing"

    legacy_video_path = resolve_stored_interview_video_path(response)
    if legacy_video_path and legacy_video_path.is_file():
        question_index = response.get("question_index")
        return (
            f"/interviews/by-match/{match_id}/responses/{question_index}/video",
            "available",
        )

    if response_has_video(response):
        return None, "historical_unavailable"

    return None, "not_recorded"


class ServicePrefixMiddleware:
    """Strip the public Vercel Services prefix before FastAPI route matching."""

    def __init__(self, app, prefix: str) -> None:
        self.app = app
        self.prefix = prefix
        self.prefix_bytes = prefix.encode()

    async def __call__(self, scope, receive, send):
        if scope["type"] in {"http", "websocket"}:
            path = scope.get("path", "")
            if path == self.prefix or path.startswith(f"{self.prefix}/"):
                scope = {
                    **scope,
                    "path": path[len(self.prefix):] or "/",
                    "root_path": f"{scope.get('root_path', '')}{self.prefix}",
                }

                raw_path = scope.get("raw_path")
                if isinstance(raw_path, bytes) and raw_path.startswith(self.prefix_bytes):
                    scope["raw_path"] = raw_path[len(self.prefix_bytes):] or b"/"

        await self.app(scope, receive, send)


app = FastAPI(title="Recruitment AI API")
app.add_middleware(ServicePrefixMiddleware, prefix="/api/backend")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:3001",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(auth_router)

# ---------------------------------------------------------------------------
# Shared GPT + embedding helpers (same logic as match_core_v3.py)
# ---------------------------------------------------------------------------

def parse_jd(raw_text: str, filename: str) -> list[dict]:
    prompt = build_jd_parse_prompt(raw_text, filename)
    response = client.chat.completions.create(
        model=CHAT_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )
    return json.loads(response.choices[0].message.content)["roles"]


def parse_cv(raw_text: str) -> dict:
    prompt = build_cv_parse_prompt(raw_text)
    response = client.chat.completions.create(
        model=CHAT_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )
    return json.loads(response.choices[0].message.content)


def get_embedding(text: str) -> list[float]:
    response = client.embeddings.create(model=EMBED_MODEL, input=text)
    return response.data[0].embedding


def cosine_similarity(a: list[float], b: list[float]) -> float:
    a, b = np.array(a), np.array(b)
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


def normalize_skill(skill: str) -> str:
    """Normalize skill labels before exact, alias, or embedding comparison."""
    lowered = (skill or "").lower().strip()
    standardized = re.sub(r"[&/+\-]+", " ", lowered)
    standardized = re.sub(r"[^a-z0-9]+", " ", standardized)
    return " ".join(standardized.split())


_RAW_SKILL_ALIASES = {
    "ai/ml": [
        "ai ml",
        "artificial intelligence",
        "machine learning",
        "natural language processing",
        "computer vision",
        "deep learning",
        "large language models",
        "generative ai",
    ],
    "ai": ["artificial intelligence"],
    "ml": ["machine learning"],
    "nlp": ["natural language processing"],
    "cv": ["computer vision"],
    "dl": ["deep learning"],
    "llm": ["large language model"],
    "llms": ["large language models", "generative ai"],
    "rag": ["retrieval augmented generation"],
    "rpa": ["robotic process automation"],
    "etl": ["extract transform load"],
    "elt": ["extract load transform"],
    "bi": ["business intelligence"],
    "erp": ["enterprise resource planning"],
    "crm": ["customer relationship management"],
    "api": ["application programming interface"],
    "rest": ["restful api web services"],
    "ci/cd": ["continuous integration continuous deployment"],
    "devops": ["development operations deployment"],
    "mlops": ["machine learning operations deployment"],
    "qa": ["quality assurance testing"],
    "ux": ["user experience design"],
    "ui": ["user interface design"],
    "saas": ["software as a service cloud"],
    "paas": ["platform as a service cloud"],
    "iaas": ["infrastructure as a service cloud"],
    "sql": ["structured query language database"],
    "nosql": ["non relational database"],
    "oop": ["object oriented programming"],
    "aws": ["amazon web services cloud"],
    "gcp": ["google cloud platform"],
    "azure": ["microsoft azure cloud"],
    "k8s": ["kubernetes container orchestration"],
    "tf": ["tensorflow machine learning"],
    "pytorch": ["pytorch deep learning framework"],
}


def _normalize_alias_dictionary(raw_aliases: dict[str, list[str]]) -> dict[str, set[str]]:
    return {
        normalize_skill(key): {normalize_skill(value) for value in values if normalize_skill(value)}
        for key, values in raw_aliases.items()
    }


SKILL_ALIASES = _normalize_alias_dictionary(_RAW_SKILL_ALIASES)

_DIRECT_EVIDENCE_ALIASES = {
    "ai ml": {
        "artificial intelligence", "machine learning", "ai engineer", "ml engineer",
        "natural language processing", "nlp", "computer vision", "deep learning",
    },
    "apis": {
        "api", "rest api", "rest APIs", "restful api", "fastapi",
        "api integration", "api service", "api services",
    },
    "api": {
        "apis", "rest api", "rest APIs", "restful api", "fastapi",
        "api integration", "api service", "api services",
    },
    "ci cd": {
        "github actions", "continuous integration", "continuous deployment",
        "deployment pipeline", "deployment pipelines",
    },
    "generative ai": {
        "llm", "llms", "large language model", "large language models",
        "openai api", "prompt engineering", "llm powered", "llm application",
    },
    "semantic matching": {
        "semantic matching", "semantic match pipeline", "semantic matching pipeline",
    },
    "backend integration": {
        "fastapi", "backend integration", "api integration", "backend api",
    },
}

_TRANSFERABLE_EVIDENCE_ALIASES = {
    "devops": {
        "github actions", "continuous integration", "continuous deployment",
        "ci cd", "deployment pipeline", "deployment pipelines",
    },
    "azure": {"aws", "amazon web services", "gcp", "google cloud platform"},
    "azure cloud": {"aws", "amazon web services", "gcp", "google cloud platform"},
    "azure cloud architecture": {
        "aws", "amazon web services", "gcp", "google cloud platform",
        "cloud architecture",
    },
    "azure devops": {
        "github actions", "continuous integration", "continuous deployment", "ci cd",
    },
    "data architecture": {
        "data engineering", "etl", "elt", "mongodb", "postgresql", "postgres",
    },
    "data platform": {
        "data engineering", "etl", "elt", "mongodb", "postgresql", "postgres",
    },
}

_DIRECT_EVIDENCE_ONLY_SKILLS = {
    "microsoft copilot studio",
    "copilot studio",
    "azure ai foundry",
    "snowflake",
    "power bi",
    "powerbi",
    "power automate",
    "azure ai services",
}


def skill_alias_terms(skill: str) -> set[str]:
    normalized = normalize_skill(skill)
    terms = {normalized} if normalized else set()
    terms.update(SKILL_ALIASES.get(normalized, set()))
    return terms


def expand_skill_abbreviations(skill: str) -> str:
    """
    Expand common tech abbreviations before embedding.
    Short abbreviations have weak embeddings - expanding them improves
    semantic matching significantly.
    """
    aliases = skill_alias_terms(skill)
    return " ".join(sorted(aliases)) if aliases else skill


def find_exact_skill_match(required_skill: str, candidate_skills: list[str]) -> str | None:
    normalized_required = normalize_skill(required_skill)
    for candidate_skill in candidate_skills:
        if normalize_skill(candidate_skill) == normalized_required:
            return candidate_skill
    return None


def find_alias_skill_match(required_skill: str, candidate_skills: list[str]) -> str | None:
    required_terms = skill_alias_terms(required_skill)
    for candidate_skill in candidate_skills:
        candidate_terms = skill_alias_terms(candidate_skill)
        if required_terms.intersection(candidate_terms):
            return candidate_skill
    return None


def build_candidate_skill_evidence(candidate: dict) -> list[dict]:
    """Collect factual, source-labelled resume text for deterministic matching."""
    evidence = []

    def add(source: str, value) -> None:
        text = str(value or "").strip()
        if text:
            evidence.append({"source": source, "text": text})

    for skill in candidate.get("skills") or []:
        add("technical_skills", skill)
    add("professional_summary", candidate.get("summary"))
    for role in candidate.get("work_experience") or []:
        add("professional_experience", role.get("title"))
        for highlight in role.get("highlights") or []:
            add("professional_experience", highlight)
    for project in candidate.get("projects") or []:
        if isinstance(project, dict):
            add("projects", project.get("name"))
            add("projects", project.get("description"))
            for technology in project.get("technologies") or []:
                add("projects", technology)
            for highlight in project.get("highlights") or []:
                add("projects", highlight)
        else:
            add("projects", project)
    for achievement in candidate.get("key_achievements") or []:
        add("professional_experience", achievement)
    for certification in candidate.get("certifications") or []:
        add("certifications", certification)
    for line in re.split(r"[\r\n]+", candidate.get("cv_raw") or ""):
        add("full_resume", line)
    return evidence


def _evidence_matches(terms: set[str], evidence: list[dict]) -> list[dict]:
    normalized_terms = {normalize_skill(term) for term in terms if normalize_skill(term)}
    matches = []
    for item in evidence:
        normalized_text = f" {normalize_skill(item.get('text', ''))} "
        if any(f" {term} " in normalized_text for term in normalized_terms):
            matches.append(item)
    return matches


def find_resume_evidence(required_skill: str, evidence: list[dict]) -> dict | None:
    normalized_required = normalize_skill(required_skill)
    terms = {normalized_required}
    terms.update(_DIRECT_EVIDENCE_ALIASES.get(normalized_required, set()))
    matches = _evidence_matches(terms, evidence)
    if not matches:
        return None
    return {
        "matched_with": required_skill,
        "evidence_sources": list(dict.fromkeys(item["source"] for item in matches)),
        "evidence": [item["text"] for item in matches[:3]],
    }


def find_transferable_resume_evidence(
    required_skill: str, evidence: list[dict]
) -> dict | None:
    normalized_required = normalize_skill(required_skill)
    terms = _TRANSFERABLE_EVIDENCE_ALIASES.get(normalized_required, set())
    matches = _evidence_matches(terms, evidence)
    if not matches:
        return None
    matched_term = next(
        (
            term for term in sorted(terms)
            if _evidence_matches({term}, matches)
        ),
        "related experience",
    )
    return {
        "closest_match": matched_term,
        "evidence_sources": list(dict.fromkeys(item["source"] for item in matches)),
        "evidence": [item["text"] for item in matches[:3]],
    }


def log_skill_alias_diagnostic(
    required_skill: str,
    normalized_required: str,
    candidate_normalized_skills: list[str],
    alias_match_found: bool,
    matched_with: str | None,
) -> None:
    if normalized_required == "ai ml":
        print(
            "[skill-analysis] "
            f"Required skill: {required_skill}; "
            f"Normalized required skill: {normalized_required}; "
            f"Candidate normalized skills: {candidate_normalized_skills}; "
            f"Alias match found: {alias_match_found}; "
            f"Matched with: {matched_with or 'None'}"
        )


def build_skill_analysis_result(
    match_id: str,
    job_skills: list[str],
    cand_skills: list[str],
    job_embeddings: list[list[float]] | None = None,
    cand_embeddings: list[list[float]] | None = None,
    candidate_evidence: list[dict] | None = None,
) -> dict:
    matched = []
    partial = []
    missing = []
    candidate_normalized_skills = [normalize_skill(skill) for skill in cand_skills]
    candidate_evidence = candidate_evidence or []

    for i, job_skill in enumerate(job_skills):
        normalized_required = normalize_skill(job_skill)
        exact_match = find_exact_skill_match(job_skill, cand_skills)
        if exact_match:
            matched.append({
                "required": job_skill,
                "matched_with": exact_match,
                "similarity": 1.0,
                "type": "strong",
                "classification": "matched",
                "match_reason": "exact_normalized",
                "evidence_sources": ["technical_skills"],
                "evidence": [exact_match],
                "confidence": "high",
            })
            log_skill_alias_diagnostic(
                job_skill,
                normalized_required,
                candidate_normalized_skills,
                False,
                exact_match,
            )
            continue

        alias_match = find_alias_skill_match(job_skill, cand_skills)
        if alias_match:
            matched.append({
                "required": job_skill,
                "matched_with": alias_match,
                "similarity": 1.0,
                "type": "strong",
                "classification": "matched",
                "match_reason": "category_alias",
                "evidence_sources": ["technical_skills"],
                "evidence": [alias_match],
                "confidence": "high",
            })
            log_skill_alias_diagnostic(
                job_skill,
                normalized_required,
                candidate_normalized_skills,
                True,
                alias_match,
            )
            continue

        resume_match = find_resume_evidence(job_skill, candidate_evidence)
        if resume_match:
            matched.append({
                "required": job_skill,
                "matched_with": resume_match["matched_with"],
                "similarity": 1.0,
                "type": "strong",
                "classification": "experience_backed_match",
                "match_reason": "resume_evidence",
                "evidence_sources": resume_match["evidence_sources"],
                "evidence": resume_match["evidence"],
                "confidence": "high",
            })
            continue

        transferable_match = find_transferable_resume_evidence(
            job_skill, candidate_evidence
        )
        if transferable_match:
            partial.append({
                "required": job_skill,
                "closest_match": transferable_match["closest_match"],
                "similarity": 0.7,
                "type": "partial",
                "classification": "transferable",
                "match_reason": "controlled_transferable_evidence",
                "evidence_sources": transferable_match["evidence_sources"],
                "evidence": transferable_match["evidence"],
                "confidence": "medium",
            })
            continue

        if normalized_required in _DIRECT_EVIDENCE_ONLY_SKILLS:
            missing.append({
                "required": job_skill,
                "closest_match": None,
                "similarity": 0,
                "type": "missing",
                "classification": "gap",
                "match_reason": "no_direct_resume_evidence",
            })
            continue

        best_score = 0.0
        best_cand_skill = None
        if job_embeddings is not None and cand_embeddings is not None:
            for j, cand_skill in enumerate(cand_skills):
                score = cosine_similarity(job_embeddings[i], cand_embeddings[j])
                if score > best_score:
                    best_score = score
                    best_cand_skill = cand_skill

        log_skill_alias_diagnostic(
            job_skill,
            normalized_required,
            candidate_normalized_skills,
            False,
            best_cand_skill,
        )

        if best_score >= 0.80:
            matched.append({
                "required": job_skill,
                "matched_with": best_cand_skill,
                "similarity": round(best_score, 3),
                "type": "strong",
                "classification": "matched",
                "match_reason": "embedding_similarity",
                "confidence": "medium",
            })
        elif best_score >= 0.65:
            partial.append({
                "required": job_skill,
                "closest_match": best_cand_skill,
                "similarity": round(best_score, 3),
                "type": "partial",
                "classification": "transferable",
                "match_reason": "embedding_similarity",
                "confidence": "medium",
            })
        else:
            missing.append({
                "required": job_skill,
                "closest_match": best_cand_skill,
                "similarity": round(best_score, 3),
                "type": "missing",
                "classification": "gap",
                "match_reason": "embedding_similarity" if best_cand_skill else "no_match",
                "confidence": "high",
            })

    semantic_score = round(
        ((len(matched) + 0.5 * len(partial)) / len(job_skills)) * 100
    ) if job_skills else 0

    return {
        "match_id": match_id,
        "semantic_skill_score": semantic_score,
        "matched": matched,
        "partial": partial,
        "missing": missing,
        "summary": (
            f"{len(matched)} strong match(es), {len(partial)} transferable "
            f"skill(s), {len(missing)} gap(s) out of {len(job_skills)} required skills"
        ),
    }

def build_vector_search_pipeline(query_vector: list[float], result_limit: int) -> list[dict]:
    limit = max(1, result_limit)
    return [
        {
            "$vectorSearch": {
                "index": "autoembed_index",
                "path": "embedding",
                "queryVector": query_vector,
                "numCandidates": max(100, limit),
                "limit": limit,
            }
        },
        {
            "$addFields": {
                "score": {"$meta": "vectorSearchScore"}
            }
        },
    ]


async def search_candidate_vectors(
    query_vector: list[float], result_limit: int
) -> list[dict]:
    """Return candidate Mongo documents in vector-score order."""
    if VECTOR_BACKEND == "mongodb":
        pipeline = build_vector_search_pipeline(query_vector, result_limit)
        return await candidates_collection.aggregate(pipeline).to_list(length=None)

    vector_results = await asyncio.to_thread(
        search_weaviate_candidates, query_vector, weaviate_overfetch_limit(result_limit)
    )
    hydrated = await hydrate_vector_results(
        vector_results, "candidate_id", candidates_collection
    )
    return hydrated[:result_limit]


async def search_job_vectors(
    query_vector: list[float], result_limit: int
) -> list[dict]:
    """Return job Mongo documents in vector-score order."""
    if VECTOR_BACKEND == "mongodb":
        pipeline = build_vector_search_pipeline(query_vector, result_limit)
        return await jobs_collection.aggregate(pipeline).to_list(length=None)

    vector_results = await asyncio.to_thread(
        search_weaviate_jobs, query_vector, weaviate_overfetch_limit(result_limit)
    )
    hydrated = await hydrate_vector_results(vector_results, "job_id", jobs_collection)
    return hydrated[:result_limit]


def weaviate_overfetch_limit(result_limit: int) -> int:
    """Allow Mongo hydration to discard orphaned vector records safely."""
    return max(100, result_limit * 5)


async def hydrate_vector_results(
    vector_results: list[dict], id_field: str, collection
) -> list[dict]:
    """Hydrate Weaviate IDs from Mongo while preserving ranking and scores."""
    ranked_ids = [
        ObjectId(item[id_field])
        for item in vector_results
        if ObjectId.is_valid(item.get(id_field, ""))
    ]
    if not ranked_ids:
        return []

    documents = await collection.find({"_id": {"$in": ranked_ids}}).to_list(
        length=None
    )
    by_id = {document["_id"]: document for document in documents}
    hydrated = []
    for item in vector_results:
        raw_id = item.get(id_field, "")
        if not ObjectId.is_valid(raw_id):
            continue
        document = by_id.get(ObjectId(raw_id))
        if document is not None:
            hydrated.append({**document, "score": item.get("score", 0)})
    return hydrated


async def match_candidates_for_job(job_id: ObjectId, job: dict) -> int:
    """Persist current vector matches for one existing MongoDB job."""
    candidate_count = await candidates_collection.count_documents({})
    print(f"[matching] backend={VECTOR_BACKEND}")
    print(f"[matching] job_id={job_id}")
    if not candidate_count:
        print("[matching] vector_results=0")
        print("[matching] hydrated_candidates=0")
        print("[matching] persisted_matches=0")
        return 0

    embedding = job.get("embedding") or []
    if not embedding:
        raise HTTPException(422, "Job does not contain a searchable embedding")

    if VECTOR_BACKEND == "weaviate":
        vector_results = await asyncio.to_thread(
            search_weaviate_candidates,
            embedding,
            weaviate_overfetch_limit(candidate_count),
        )
        print(f"[matching] vector_results={len(vector_results)}")
        top_candidates = await hydrate_vector_results(
            vector_results, "candidate_id", candidates_collection
        )
        top_candidates = top_candidates[:candidate_count]
    else:
        top_candidates = await search_candidate_vectors(embedding, candidate_count)
        print(f"[matching] vector_results={len(top_candidates)}")

    print(f"[matching] hydrated_candidates={len(top_candidates)}")
    persisted_matches = 0
    for candidate in top_candidates:
        await upsert_match(job_id, candidate["_id"], candidate.get("score", 0))
        persisted_matches += 1
    print(f"[matching] persisted_matches={persisted_matches}")
    return persisted_matches


async def upsert_match(job_id: ObjectId, candidate_id: ObjectId, match_score: float) -> None:
    now = datetime.now(timezone.utc)
    match_filter = {"job_id": job_id, "candidate_id": candidate_id}
    update = {
        "$set": {
            "match_score": round(match_score, 4),
            "updated_at": now,
        },
        "$setOnInsert": {
            "status": "Matched",
            "status_note": "",
            "created_at": now,
        },
    }

    try:
        await matches_collection.update_one(match_filter, update, upsert=True)
    except DuplicateKeyError:
        await matches_collection.update_one(match_filter, {"$set": update["$set"]})


async def deduplicate_match_documents() -> None:
    pipeline = [
        {"$sort": {"updated_at": -1, "created_at": -1}},
        {
            "$group": {
                "_id": {"job_id": "$job_id", "candidate_id": "$candidate_id"},
                "keep_id": {"$first": "$_id"},
                "ids": {"$push": "$_id"},
                "count": {"$sum": 1},
            }
        },
        {"$match": {"count": {"$gt": 1}}},
    ]

    async for group in matches_collection.aggregate(pipeline):
        duplicate_ids = [match_id for match_id in group["ids"] if match_id != group["keep_id"]]
        if duplicate_ids:
            await matches_collection.delete_many({"_id": {"$in": duplicate_ids}})


@app.on_event("startup")
async def ensure_match_uniqueness() -> None:
    analysis_status = recording_analysis_startup_status()
    print(
        "[recording observations] startup "
        f"face_package={analysis_status['face_landmarker_package']} "
        f"face_model={analysis_status['face_landmarker_model']} "
        f"speaker_package={analysis_status['speaker_diarization_package']} "
        f"speaker_token={analysis_status['speaker_diarization_token']} "
        f"speaker_model={analysis_status['speaker_diarization_model']}"
    )
    await deduplicate_match_documents()
    await matches_collection.create_index(
        [("job_id", 1), ("candidate_id", 1)],
        unique=True,
        name="unique_job_candidate_match",
    )
    await generated_profiles_collection.create_index(
        [("match_id", 1)],
        unique=True,
        name="unique_profile_match",
    )
    await recruiter_users_collection.create_index(
        [("email_normalized", 1)],
        unique=True,
        name="unique_recruiter_email",
    )
    await password_reset_tokens_collection.create_index(
        [("token_hash", 1)],
        unique=True,
        name="unique_password_reset_token",
    )
    await password_reset_tokens_collection.create_index(
        [("expires_at", 1)],
        expireAfterSeconds=0,
        name="expire_password_reset_tokens",
    )
    if VECTOR_BACKEND == "weaviate":
        try:
            await asyncio.to_thread(connect_to_weaviate)
            await asyncio.to_thread(ensure_weaviate_collections)
        except Exception:
            await asyncio.to_thread(close_weaviate)
            raise


@app.on_event("shutdown")
async def close_vector_backend() -> None:
    if VECTOR_BACKEND == "weaviate":
        await asyncio.to_thread(close_weaviate)


def validate_upload_extension(filename: Optional[str]) -> str:
    """Return a safe supported suffix or reject the upload before writing it."""
    suffix = Path(filename or "").suffix.lower()
    if suffix not in {".pdf", ".docx"}:
        raise HTTPException(
            status_code=415,
            detail="Unsupported file type. Please upload a PDF or DOCX file.",
        )
    return suffix


async def save_uploaded_file_to_temp(upload_file: UploadFile) -> tuple[str, str, bytes]:
    """Return a temporary path, content hash, and unchanged upload bytes.
    The hash is an MD5 of the raw file bytes — used to detect duplicate uploads
    regardless of filename. Returned alongside the path so the caller can check
    for duplicates before doing any GPT/embedding work.
    """
    suffix = validate_upload_extension(upload_file.filename)
    contents = await upload_file.read()
    content_hash = hashlib.md5(contents).hexdigest()
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp_path = tmp.name
            tmp.write(contents)
        return tmp_path, content_hash, contents
    except Exception:
        if tmp_path:
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except OSError:
                pass
        raise


def _remove_file_best_effort(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        print(f"[candidate upload] Could not remove incomplete original CV {path}: {exc}")


async def persist_candidate_with_original_cv(
    candidate_doc: dict,
    original_cv_bytes: bytes,
    original_filename: Optional[str],
) -> ObjectId:
    """Store the original CV before atomically inserting its candidate reference."""
    candidate_id = ObjectId()
    original_cv_key = candidate_cv_storage_key(
        candidate_id,
        original_filename or "candidate.pdf",
    )
    original_cv_path = resolve_candidate_cv_storage_key(original_cv_key)
    if not original_cv_path:
        raise HTTPException(500, "Could not create a safe original CV storage path")

    try:
        original_cv_path.parent.mkdir(parents=True, exist_ok=True)
        original_cv_path.write_bytes(original_cv_bytes)
    except OSError as exc:
        _remove_file_best_effort(original_cv_path)
        raise HTTPException(500, "Could not safely store the original CV") from exc

    candidate_with_original = {
        **candidate_doc,
        "_id": candidate_id,
        "original_cv_storage_key": original_cv_key,
    }
    try:
        await candidates_collection.insert_one(candidate_with_original)
    except Exception:
        _remove_file_best_effort(original_cv_path)
        raise

    return candidate_id


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.post("/matches/{match_id}/analyse", dependencies=[Depends(get_current_recruiter)])
async def analyse_match(match_id: str):
    """
    Run decision intelligence analysis on a specific match.
    Uses GPT to reason about the fit between candidate and job,
    returning structured scores and a detailed recommendation.
    """
    # Fetch the match record
    match = await matches_collection.find_one({"_id": ObjectId(match_id)})
    if not match:
        raise HTTPException(404, f"No match found with id {match_id}")

    # Fetch the full job and candidate
    job = await jobs_collection.find_one({"_id": match["job_id"]})
    candidate = await candidates_collection.find_one({"_id": match["candidate_id"]})

    if not job or not candidate:
        raise HTTPException(404, "Job or candidate not found for this match")

    # Build the analysis prompt
    job_skills = job.get("required_skills", [])
    cand_skills = candidate.get("skills", [])
    candidate_evidence = build_candidate_skill_evidence(candidate)
    job_years = job.get("min_years_experience") or 0
    cand_years = candidate.get("years_experience") or 0

    # Calculate skill coverage: exact normalized match, alias/category match, then embeddings.
    skill_analysis = build_skill_analysis_result(
        match_id, job_skills, cand_skills, candidate_evidence=candidate_evidence
    )
    if job_skills and cand_skills:
        try:
            expanded_job_skills = [expand_skill_abbreviations(s) for s in job_skills]
            expanded_cand_skills = [expand_skill_abbreviations(s) for s in cand_skills]
            all_skills_to_embed = expanded_job_skills + expanded_cand_skills
            embed_response = client.embeddings.create(
                model=EMBED_MODEL, input=all_skills_to_embed
            )
            embeddings = [r.embedding for r in embed_response.data]
            job_embeddings = embeddings[:len(job_skills)]
            cand_embeddings = embeddings[len(job_skills):]
            skill_analysis = build_skill_analysis_result(
                match_id,
                job_skills,
                cand_skills,
                job_embeddings,
                cand_embeddings,
                candidate_evidence,
            )
        except Exception:
            # Keep deterministic exact/alias results if embedding fallback is unavailable.
            pass

    matched_skills = [item["required"] for item in skill_analysis["matched"]]
    missing_skills = [item["required"] for item in skill_analysis["missing"]]

    # Calculate tech match %
    tech_match = skill_analysis["semantic_skill_score"] if job_skills else 0

    # Calculate experience match - combines years and domain relevance
    if job_years == 0:
        years_score = 100
    elif cand_years >= job_years:
        years_score = 100
    else:
        years_score = round((cand_years / job_years) * 100)

    # Domain relevance - does the candidate's domain experience match the job domain?
    job_domain = (job.get("domain") or "").lower()
    cand_domains = [d.lower() for d in candidate.get("domain_experience", [])]
    job_title_lower = (job.get("title") or "").lower()
    cand_summary_lower = (candidate.get("summary") or "").lower()

    # Check domain overlap - embed and compare for semantic match
    domain_score = 50  # default: partial match assumed

    if job_domain and cand_domains:
        try:
            # Embed job domain against candidate domains
            domain_texts = [job_domain] + cand_domains
            domain_embeds = client.embeddings.create(
                model=EMBED_MODEL, input=domain_texts
            )
            domain_vecs = [r.embedding for r in domain_embeds.data]
            job_domain_vec = domain_vecs[0]
            cand_domain_vecs = domain_vecs[1:]

            best_domain_sim = max(
                cosine_similarity(job_domain_vec, cv)
                for cv in cand_domain_vecs
            )
            domain_score = round(best_domain_sim * 100)
        except Exception:
            domain_score = 50
    elif job_domain in cand_summary_lower or job_title_lower in cand_summary_lower:
        domain_score = 75

    # Final experience match: 60% weight on years, 40% weight on domain relevance
    exp_match = round(0.60 * years_score + 0.40 * domain_score)

    prompt = f"""You are a senior recruitment consultant with expertise in talent assessment.
Analyse the fit between this candidate and job, then provide a factual assessment report.

JOB DETAILS:
Title: {job.get('title')}
Domain: {job.get('domain')}
Required Skills: {', '.join(job_skills)}
Minimum Experience: {job_years} years
Summary: {job.get('summary', '')}

CANDIDATE DETAILS:
Name: {candidate.get('name')}
Summary: {candidate.get('summary', '')}
Skills: {', '.join(cand_skills)}
Years Experience: {cand_years}
Domain Experience: {', '.join(candidate.get('domain_experience', []))}
Work Rights: {candidate.get('work_rights', 'Not specified')}
Notice Period: {candidate.get('notice_period', 'Not specified')}

CALCULATED METRICS:
Overall Match Score: {round(match.get('match_score', 0) * 100)}%
Technical Skills Match: {tech_match}% ({len(matched_skills)}/{len(job_skills)} required skills matched)
Matched Skills: {', '.join(matched_skills) if matched_skills else 'None'}
Missing Skills: {', '.join(missing_skills) if missing_skills else 'None'}
Experience Match: {exp_match}% ({cand_years} total years experience, {job_years} years required for this role; score combines years ({years_score}%) and domain relevance ({domain_score}%))

IMPORTANT: Do not make hiring recommendations or decisions. 
Present facts objectively. Let the recruiter decide.

Return ONLY valid JSON, no markdown, no code fences:
{{
  "ai_summary": "3-4 sentence factual paragraph about this candidate's background and how it relates to this specific role. Mention their relevant experience, domain background, and key skills. Note any gaps factually without judging. Do not say 'recommend', 'suitable', 'poor fit', or make any hiring decision.",
  "strengths": [
    "factual strength relevant to this role",
    "factual strength 2",
    "factual strength 3"
  ],
  "risks": [
    "factual gap or consideration 1",
    "factual gap or consideration 2"
  ],
  "tech_match_percentage": {tech_match},
  "exp_match_percentage": {exp_match},
  "matched_skills": {json.dumps(matched_skills)},
  "missing_skills": {json.dumps(missing_skills)},
  "interview_questions": [
    "Targeted question based on a gap or area to probe",
    "Another targeted question"
  ]
}}"""

    response = client.chat.completions.create(
        model="gpt-4o",          # use the stronger model for reasoning
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
    )

    analysis = json.loads(response.choices[0].message.content)

    # Store the analysis back on the match record so we don't re-run it every time
    await matches_collection.update_one(
        {"_id": ObjectId(match_id)},
        {"$set": {
            "analysis": analysis,
            "analysis_generated_at": datetime.now(timezone.utc),
        }}
    )

    return {
        "match_id": match_id,
        "analysis": analysis,
    }

@app.get("/matches/{match_id}/skill-analysis", dependencies=[Depends(get_current_recruiter)])
async def get_skill_analysis(match_id: str):
    """
    Semantic skill matching using embeddings.
    Compares each required job skill against every candidate skill
    using cosine similarity on OpenAI embeddings — not keyword matching.
    Returns matched (strong), partial (transferable), and missing skills
    with similarity scores. Results are cached on the match document.
    """
    m = await matches_collection.find_one({"_id": ObjectId(match_id)})
    if not m:
        raise HTTPException(404, "Match not found")

    # Always recalculate so older cached alias results cannot stay stale.

    job = await jobs_collection.find_one({"_id": m["job_id"]})
    candidate = await candidates_collection.find_one({"_id": m["candidate_id"]})

    if not job or not candidate:
        raise HTTPException(404, "Job or candidate not found")

    job_skills = job.get("required_skills", [])
    cand_skills = candidate.get("skills", [])
    candidate_evidence = build_candidate_skill_evidence(candidate)

    if not job_skills:
        result = {
            "match_id": match_id,
            "semantic_skill_score": 0,
            "matched": [],
            "partial": [],
            "missing": [
                {"required": s, "similarity": 0, "type": "missing", "match_reason": "no_candidate_skills"}
                for s in job_skills
            ],
            "summary": "No skills available for comparison"
        }
        await matches_collection.update_one(
            {"_id": ObjectId(match_id)},
            {"$set": {
                "skill_analysis": result,
                "skill_analysis_at": datetime.now(timezone.utc),
            }}
        )
        return result

    result = build_skill_analysis_result(
        match_id,
        job_skills,
        cand_skills,
        candidate_evidence=candidate_evidence,
    )
    if cand_skills:
        try:
            # Embed all skills in one batch call for the existing semantic fallback.
            expanded_job_skills = [expand_skill_abbreviations(s) for s in job_skills]
            expanded_cand_skills = [expand_skill_abbreviations(s) for s in cand_skills]
            all_skills = expanded_job_skills + expanded_cand_skills
            embed_response = client.embeddings.create(model=EMBED_MODEL, input=all_skills)
            embeddings = [r.embedding for r in embed_response.data]
            job_embeddings = embeddings[:len(job_skills)]
            cand_embeddings = embeddings[len(job_skills):]
            result = build_skill_analysis_result(
                match_id,
                job_skills,
                cand_skills,
                job_embeddings,
                cand_embeddings,
                candidate_evidence,
            )
        except Exception:
            # Deterministic explicit, resume-evidence, and alias matches remain usable.
            pass

    # Cache on the match document so subsequent calls are instant
    await matches_collection.update_one(
        {"_id": ObjectId(match_id)},
        {"$set": {
            "skill_analysis": result,
            "skill_analysis_at": datetime.now(timezone.utc),
        }}
    )

    return result


@app.post("/interviews/schedule/{match_id}", dependencies=[Depends(get_current_recruiter)])
async def schedule_interview(match_id: str):
    """
    Schedule an AI interview for a shortlisted candidate.
    Generates questions, creates interview document, sends invitation email.
    Updates match status to Interview Sent.
    """
    match = await matches_collection.find_one({"_id": ObjectId(match_id)})
    if not match:
        raise HTTPException(404, "Match not found")

    candidate = await candidates_collection.find_one({"_id": match["candidate_id"]})
    job = await jobs_collection.find_one({"_id": match["job_id"]})

    if not candidate or not job:
        raise HTTPException(404, "Candidate or job not found")
    if not candidate.get("email"):
        raise HTTPException(400, "Candidate has no email address on file")

    # Always generate fresh questions from the actual job description
    # Never reuse cached questions — they may be from a different context
    job_description = job.get("description_raw") or ""
    job_title = job.get("title") or ""
    job_skills = job.get("required_skills", [])
    job_domain = job.get("domain") or "general"
    cand_skills = candidate.get("skills", [])
    cand_summary = candidate.get("summary") or ""
    cand_years = candidate.get("years_experience") or 0

    prompt = f"""You are a senior technical interviewer preparing questions for a candidate interview.

JOB DETAILS:
Title: {job_title}
Domain: {job_domain}
Required skills: {', '.join(job_skills)}
Job description excerpt: {job_description[:1500]}

CANDIDATE PROFILE:
Summary: {cand_summary}
Skills: {', '.join(cand_skills)}
Years of experience: {cand_years}

Generate exactly 5 interview questions that are:
1. Directly relevant to THIS specific job description and required skills
2. Tailored to this candidate's background (probe gaps, explore strengths)
3. A mix of technical questions (testing specific required skills) and behavioural questions
4. Open-ended — no yes/no questions
5. Each question must be answerable verbally in approximately 30 seconds.
6. Questions should be concise and focused.
7. Avoid questions that require lengthy explanations or multi-part answers.

For technical questions, reference specific technologies from the required skills list.
For behavioural questions, reference the job domain ({job_domain}) and expected responsibilities.

Return ONLY a valid JSON array of exactly 5 question strings. No other text, no numbering, no markdown.
Example format: ["Question one?", "Question two?", "Question three?", "Question four?", "Question five?"]"""

    q_response = client.chat.completions.create(
        model="gpt-4o",          # use stronger model for question quality
        messages=[{"role": "user", "content": prompt}],
        temperature=0.6,          # slight creativity for varied questions
    )

    raw = q_response.choices[0].message.content.strip()
    # Strip markdown fences if GPT adds them
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    questions = json.loads(raw.strip())

    if not isinstance(questions, list) or len(questions) == 0:
        raise HTTPException(500, "Failed to generate interview questions")

    token = secrets.token_urlsafe(48)
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=7)

    interview_doc = {
        "match_id": ObjectId(match_id),
        "job_id": match["job_id"],
        "candidate_id": match["candidate_id"],
        "candidate_name": candidate.get("name"),
        "candidate_email": candidate.get("email"),
        "job_title": job.get("title"),
        "token": token,
        "questions": questions,
        "time_per_question_seconds": 30,
        "status": "Invited",
        "responses": [],
        "assessment": None,
        "video_analysis_status": "pending",
        "video_analysis": None,
        "scheduled_at": None,
        "expires_at": expires_at,
        "created_at": now,
    }
    await interviews_collection.insert_one(interview_doc)

    await matches_collection.update_one(
        {"_id": ObjectId(match_id)},
        {"$set": {"status": "Interview Sent", "updated_at": now}}
    )

    interview_url = f"{FRONTEND_URL}/interview/{token}"
    email_html = f"""
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;">
      <h2 style="color:#7B1111;">Interview Invitation - {job.get('title')}</h2>
      <p>Dear {candidate.get('name')},</p>
      <p>Congratulations! You have been shortlisted for the
         <strong>{job.get('title')}</strong> position.</p>
      <p>Please complete an AI-powered screening interview at your convenience.
         The interview contains <strong>{len(questions)} questions</strong>. You will have
         <strong>30 seconds</strong> to answer each question. The interview should take
         approximately 3-4 minutes to complete.</p>
      <div style="text-align:center;margin:30px 0;">
        <a href="{interview_url}"
           style="background:#7B1111;color:#fff;padding:14px 28px;
                  text-decoration:none;border-radius:8px;font-size:16px;">
          Start Your Interview
        </a>
      </div>
      <p style="color:#666;">This link expires on
         {expires_at.strftime('%B %d, %Y')}.</p>
      <p>Best regards,<br>iSOFT Recruitment Team</p>
    </div>"""

    email_sent = send_email(
        to_address=candidate.get("email"),
        subject=f"Interview Invitation - {job.get('title')}",
        html_body=email_html,
    )

    return {
        "message": "Interview scheduled"
                   + (" and invitation sent" if email_sent else
                      " (email not sent - check SMTP config)"),
        "token": token,
        "interview_url": interview_url,
        "candidate_email": candidate.get("email"),
        "expires_at": expires_at.isoformat(),
        "email_sent": email_sent,
    }


@app.get("/interviews/by-match/{match_id}", dependencies=[Depends(get_current_recruiter)])
async def get_interview_by_match(match_id: str):
    """Recruiter views interview results for a specific match."""
    if not ObjectId.is_valid(match_id):
        raise HTTPException(404, "No interview found for this match")

    interview = await interviews_collection.find_one(
        {"match_id": ObjectId(match_id)}
    )
    if not interview:
        raise HTTPException(404, "No interview found for this match")

    match = await matches_collection.find_one({"_id": ObjectId(match_id)})
    profile_match_score = None
    if match and match.get("match_score") is not None:
        profile_match_score = round(match.get("match_score", 0) * 100)

    video_analysis = interview.get("video_analysis")
    video_analysis_status = (
        interview.get("video_analysis_status")
        or (video_analysis or {}).get("video_analysis_status")
        or ("completed" if video_analysis else "pending")
    )
    response_payloads = []
    for response in interview.get("responses", []):
        video_url, video_playback_status = response_video_playback(match_id, response)
        response_payloads.append({
            "question_index": response.get("question_index"),
            "question": response.get("question"),
            "transcript": response.get("transcript"),
            "submitted_at": response.get("submitted_at"),
            "video_observations": response.get("video_observations"),
            "video_url": video_url,
            "video_available": response_has_video(response),
            "video_playback_status": video_playback_status,
            "video_size_bytes": response.get("video_size_bytes"),
            "video_duration_seconds": response.get("video_duration_seconds"),
            "video_content_type": response.get("video_content_type"),
            # Deliberately exclude frames_b64, video_storage_key, and legacy
            # video_path from this normal recruiter response.
        })

    return {
        "interview_id": str(interview["_id"]),
        "candidate_name": interview["candidate_name"],
        "candidate_email": interview["candidate_email"],
        "job_title": interview["job_title"],
        "status": interview["status"],
        "profile_match_score": profile_match_score,
        "questions": interview.get("questions", []),
        "responses": response_payloads,
        "assessment": interview.get("assessment"),
        "video_analysis_status": video_analysis_status,
        "video_analysis": video_analysis,
        "cv_consistency": interview.get("cv_consistency"),
        "expires_at": interview["expires_at"].isoformat(),
        "created_at": interview["created_at"].isoformat(),
    }


@app.get("/interviews/by-match/{match_id}/responses/{question_index}/video", dependencies=[Depends(get_current_recruiter)])
async def get_interview_response_video(match_id: str, question_index: int):
    """Controlled recruiter playback endpoint for persisted interview response video."""
    if not ObjectId.is_valid(match_id):
        raise HTTPException(404, "No interview found for this match")

    interview = await interviews_collection.find_one({"match_id": ObjectId(match_id)})
    if not interview:
        raise HTTPException(404, "No interview found for this match")

    questions = interview.get("questions", [])
    if question_index < 0 or question_index >= len(questions):
        raise HTTPException(404, "Interview response not found")

    response = next(
        (
            r for r in interview.get("responses", [])
            if r.get("question_index") == question_index
        ),
        None,
    )
    if not response:
        raise HTTPException(404, "Interview response not found")

    video_path = resolve_stored_interview_video_path(response)
    if not video_path or not video_path.exists() or not video_path.is_file():
        raise HTTPException(404, "Stored video file not found")

    media_type = response.get("video_content_type") or "video/webm"
    if not media_type.startswith("video/"):
        media_type = "video/webm"

    return FileResponse(
        path=str(video_path),
        media_type=media_type,
    )



@app.get("/interviews/{token}")
async def get_interview(token: str):
    """Public - candidate fetches their interview details via email link."""
    interview = await interviews_collection.find_one({"token": token})
    if not interview:
        raise HTTPException(404, "Interview not found")
    now = datetime.now(timezone.utc)
    if interview["expires_at"].replace(tzinfo=timezone.utc) < now:
        await interviews_collection.update_one(
            {"token": token}, {"$set": {"status": "Expired"}}
        )
        raise HTTPException(410, "This interview link has expired")
    if interview["status"] == "Completed":
        raise HTTPException(409, "This interview has already been completed")
    answered = len(interview.get("responses", []))
    return {
        "candidate_name": interview["candidate_name"],
        "job_title": interview["job_title"],
        "total_questions": len(interview["questions"]),
        "questions_answered": answered,
        "current_question_index": answered,
        "current_question": (
            interview["questions"][answered]
            if answered < len(interview["questions"]) else None
        ),
        "time_per_question_seconds": interview.get("time_per_question_seconds", 30),
        "status": interview["status"],
        "expires_at": interview["expires_at"].isoformat(),
    }


@app.get("/interviews/{token}/question-audio/{question_index}")
async def get_question_audio(token: str, question_index: int):
    """Returns TTS audio of the AI reading a question aloud."""
    from fastapi.responses import StreamingResponse
    import io
    interview = await interviews_collection.find_one({"token": token})
    if not interview:
        raise HTTPException(404, "Interview not found")
    questions = interview.get("questions", [])
    if question_index >= len(questions):
        raise HTTPException(400, "Question index out of range")
    speech = client.audio.speech.create(
        model="tts-1",
        voice="nova",
        input=questions[question_index],
    )
    return StreamingResponse(
        io.BytesIO(speech.content),
        media_type="audio/mpeg",
    )


@app.post("/interviews/{token}/respond")
async def submit_response(token: str, audio: UploadFile = File(...)):
    """
    Public - candidate submits audio for one question.
    Transcribes with Whisper. Returns next question or completion signal.
    """
    interview = await interviews_collection.find_one({"token": token})
    if not interview:
        raise HTTPException(404, "Interview not found")
    if interview["status"] == "Completed":
        raise HTTPException(409, "Interview already completed")
    now = datetime.now(timezone.utc)
    if interview["expires_at"].replace(tzinfo=timezone.utc) < now:
        raise HTTPException(410, "Interview link has expired")

    question_index = len(interview.get("responses", []))
    if question_index >= len(interview["questions"]):
        raise HTTPException(400, "All questions already answered")

    suffix = os.path.splitext(audio.filename or "audio.webm")[1] or ".webm"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await audio.read())
        tmp_path = tmp.name
    try:
        with open(tmp_path, "rb") as f:
            transcription = client.audio.transcriptions.create(
                model="whisper-1", file=f,
            )
        transcript = transcription.text
    finally:
        os.remove(tmp_path)

    response_doc = {
        "question_index": question_index,
        "question": interview["questions"][question_index],
        "transcript": transcript,
        "submitted_at": now.isoformat(),
    }
    new_responses = interview.get("responses", []) + [response_doc]
    all_done = len(new_responses) >= len(interview["questions"])

    await interviews_collection.update_one(
        {"token": token},
        {"$set": {
            "responses": new_responses,
            "status": "Completed" if all_done else "Started",
            "video_analysis_status": "pending",
        }}
    )

    if all_done:
        # Update match status immediately so recruiter portal shows results
        # Don't wait for assessment - transcript is available right now
        interview_doc = await interviews_collection.find_one({"token": token})
        if interview_doc and interview_doc.get("match_id"):
            await matches_collection.update_one(
                {"_id": interview_doc["match_id"]},
                {"$set": {
                    "status": "Interview Completed",
                    "updated_at": datetime.now(timezone.utc),
                }}
            )
        return {
            "completed": True,
            "message": "All questions answered. Thank you!",
            "next_question": None,
            "next_question_index": None,
        }
    return {
        "completed": False,
        "transcript_received": transcript[:100] + ("..." if len(transcript) > 100 else ""),
        "next_question_index": question_index + 1,
        "next_question": interview["questions"][question_index + 1],
    }


@app.post("/interviews/{token}/respond-video")
async def submit_video_response(token: str, video: UploadFile = File(...)):
    """
    Candidate submits video for one question.
    Extracts audio track for Whisper transcription.
    Stores video reference for later frame analysis.
    """
    interview = await interviews_collection.find_one({"token": token})
    if not interview:
        raise HTTPException(404, "Interview not found")
    if interview["status"] == "Completed":
        raise HTTPException(409, "Interview already completed")

    now = datetime.now(timezone.utc)
    if interview["expires_at"].replace(tzinfo=timezone.utc) < now:
        raise HTTPException(410, "Interview link has expired")

    question_index = len(interview.get("responses", []))
    if question_index >= len(interview["questions"]):
        raise HTTPException(400, "All questions already answered")

    # Save video to a temp file for Whisper/OpenCV, then persist a controlled copy
    suffix = ".webm"
    video_bytes = await video.read()
    video_size_bytes = len(video_bytes)
    video_storage_key = interview_video_storage_key(interview["_id"], question_index)
    persisted_video_path = resolve_interview_video_storage_key(video_storage_key)
    if not persisted_video_path:
        raise HTTPException(500, "Could not resolve interview video storage")

    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(video_bytes)
        tmp_path = tmp.name

    try:
        # Transcribe audio from the video file using Whisper
        with open(tmp_path, "rb") as f:
            transcription = client.audio.transcriptions.create(
                model="whisper-1", file=f,
            )
        transcript = transcription.text

        # Extract multiple key frames from the video for later vision analysis
        # We store base64 encoded frame snapshots per response
        frames_b64 = extract_video_frames(tmp_path, num_frames=6)
        video_duration_seconds = get_video_duration_seconds(tmp_path)

        persisted_video_path.parent.mkdir(parents=True, exist_ok=True)
        persisted_video_path.write_bytes(video_bytes)
    finally:
        os.remove(tmp_path)

    video_url = f"/interviews/by-match/{str(interview['match_id'])}/responses/{question_index}/video"
    video_content_type = video.content_type or "video/webm"
    print(
        "[video] response saved "
        f"interview_id={interview['_id']} q={question_index} "
        f"storage_key={video_storage_key} bytes={video_size_bytes} "
        f"duration_seconds={video_duration_seconds} frames={len(frames_b64)} "
        f"status={'pending' if frames_b64 else 'failed'}"
    )

    response_doc = {
        "question_index": question_index,
        "question": interview["questions"][question_index],
        "transcript": transcript,
        "video_storage_key": video_storage_key,
        "video_url": video_url,
        "video_size_bytes": video_size_bytes,
        "video_duration_seconds": video_duration_seconds,
        "video_content_type": video_content_type,
        "frames_b64": frames_b64,   # list of base64 frames, not single frame
        "submitted_at": now.isoformat(),
    }

    new_responses = interview.get("responses", []) + [response_doc]
    all_done = len(new_responses) >= len(interview["questions"])

    next_video_analysis_status = "pending" if any(r.get("frames_b64") for r in new_responses) else "failed"

    await interviews_collection.update_one(
        {"token": token},
        {"$set": {
            "responses": new_responses,
            "status": "Completed" if all_done else "Started",
            "video_analysis_status": next_video_analysis_status,
        }}
    )

    if all_done:
        interview_doc = await interviews_collection.find_one({"token": token})
        if interview_doc and interview_doc.get("match_id"):
            await matches_collection.update_one(
                {"_id": interview_doc["match_id"]},
                {"$set": {"status": "Interview Completed", "updated_at": now}}
            )
        return {"completed": True, "message": "All questions answered. Thank you!",
                "next_question": None, "next_question_index": None}

    return {
        "completed": False,
        "next_question_index": question_index + 1,
        "next_question": interview["questions"][question_index + 1],
    }


def extract_video_frames(video_path: str, num_frames: int = 6) -> list[str]:
    """
    Extract multiple frames from a video using OpenCV.
    Returns a list of base64-encoded JPEG strings.

    For a 30-second answer, extracts frames at evenly spaced intervals
    giving GPT-4o Vision a temporal view of the candidate's presentation,
    not just a single snapshot.

    Returns empty list if OpenCV is unavailable or video cannot be read.
    """
    cap = None
    try:
        import cv2
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            print("[video] OpenCV could not open the uploaded video")
            return []

        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = cap.get(cv2.CAP_PROP_FPS) or 25
        duration_sec = total_frames / fps

        if total_frames == 0 or duration_sec < 1:
            return []

        # Skip the first 1 second (candidate settling) and last 1 second
        start_sec = min(1.0, duration_sec * 0.1)
        end_sec = max(start_sec + 1, duration_sec - 1.0)

        # Evenly spaced sample points
        sample_times = [
            start_sec + (end_sec - start_sec) * i / (num_frames - 1)
            for i in range(num_frames)
        ] if num_frames > 1 else [duration_sec / 2]

        # Read forward instead of seeking by timestamp. Browser-generated VP9
        # WebMs commonly expose a 1/1000 time base and no average frame rate.
        # OpenCV can decode them sequentially but CAP_PROP_POS_MSEC seeks fail.
        frames_b64 = []
        next_sample_index = 0
        frame_index = 0
        fallback_fps = fps if 1 <= fps <= 240 else 30.0
        while next_sample_index < len(sample_times):
            ret, frame = cap.read()
            if not ret:
                break

            decoded_time = float(cap.get(cv2.CAP_PROP_POS_MSEC) or 0) / 1000.0
            timestamp = (
                decoded_time
                if decoded_time > 0 or frame_index == 0
                else frame_index / fallback_fps
            )
            frame_index += 1
            if timestamp + 1e-6 < sample_times[next_sample_index]:
                continue

            # Resize to reduce payload size - 480p is enough for presentation analysis
            h, w = frame.shape[:2]
            if w > 640:
                scale = 640 / w
                frame = cv2.resize(frame, (640, int(h * scale)))

            # Mirror the frame (front camera is typically mirrored)
            frame = cv2.flip(frame, 1)

            # Encode as JPEG
            success, buffer = cv2.imencode(
                ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75]
            )
            if success:
                frames_b64.append(
                    base64.b64encode(buffer).decode("utf-8")
                )
            next_sample_index += 1

        print(f"[video] Extracted {len(frames_b64)} frames from {duration_sec:.1f}s video")
        return frames_b64

    except ImportError:
        print("[video] OpenCV not installed - skipping frame extraction")
        return []
    except Exception as e:
        print(f"[video] Frame extraction error: {e}")
        return []
    finally:
        if cap is not None:
            cap.release()


def backfill_missing_video_frames(
    responses: list[dict], num_frames: int = 6
) -> list[dict]:
    """Recover legacy empty frame snapshots from the unchanged stored recording."""
    updated = []
    for response in responses:
        next_response = dict(response)
        if not next_response.get("frames_b64"):
            recording_path = resolve_stored_interview_video_path(next_response)
            if recording_path and recording_path.is_file():
                frames_b64 = extract_video_frames(str(recording_path), num_frames=num_frames)
                if frames_b64:
                    next_response["frames_b64"] = frames_b64
                    print(
                        "[video] Backfilled sampled frames "
                        f"q={next_response.get('question_index')} frames={len(frames_b64)}"
                    )
        updated.append(next_response)
    return updated



VIDEO_QUALITY_VALUES = {"good", "acceptable", "poor", "unknown"}
VIDEO_NOISE_VALUES = {"low", "moderate", "high", "unknown"}
VIDEO_ANALYSIS_STATUSES = {"pending", "processing", "completed", "failed", "unavailable"}
FILLER_WORDS = {"um", "uh", "erm", "ah", "like"}
FILLER_PHRASES = ["you know", "sort of", "kind of"]
PROHIBITED_VIDEO_OBSERVATION_TERMS = [
    "honest", "dishonest", "deception", "deceptive", "personality",
    "intelligence", "mental health", "emotional state", "emotion",
    "confident", "confidence", "nervous", "anxiety", "anxious",
    "cultural fit", "trustworthy", "trustworthiness", "enthusiasm",
    "disability", "ethnicity", "religion", "gender", "sexual orientation",
    "age", "health", "socioeconomic", "suitability",
]


def strip_json_fences(raw: str) -> str:
    value = (raw or "").strip()
    if value.startswith("```"):
        value = value.split("```", 2)[1]
        if value.strip().lower().startswith("json"):
            value = value.strip()[4:]
    return value.strip()


def count_filler_words(transcript: str) -> int:
    lower = (transcript or "").lower()
    phrase_count = sum(len(re.findall(rf"\b{re.escape(phrase)}\b", lower)) for phrase in FILLER_PHRASES)
    words = re.findall(r"\b[a-z']+\b", lower)
    word_count = sum(1 for word in words if word in FILLER_WORDS)
    return phrase_count + word_count


def clamp_percentage(value):
    if value is None:
        return None
    try:
        return max(0, min(100, round(float(value))))
    except (TypeError, ValueError):
        return None


def optional_number(value):
    if value is None:
        return None
    try:
        return round(float(value), 1)
    except (TypeError, ValueError):
        return None


def optional_int(value):
    if value is None:
        return None
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return None


def safe_quality(value) -> str:
    normalized = str(value or "unknown").lower().strip()
    return normalized if normalized in VIDEO_QUALITY_VALUES else "unknown"


def safe_noise(value) -> str:
    normalized = str(value or "unknown").lower().strip()
    return normalized if normalized in VIDEO_NOISE_VALUES else "unknown"


def contains_prohibited_video_observation_term(value: str) -> bool:
    lower = str(value or "").lower()
    for term in PROHIBITED_VIDEO_OBSERVATION_TERMS:
        pattern = r"\b" + re.escape(term) + r"\b"
        if re.search(pattern, lower):
            return True
    return False


def sanitize_video_observation_text(value: str) -> str:
    text_value = str(value or "").strip()
    if contains_prohibited_video_observation_term(text_value):
        return "Observation removed because it used unsupported inference language."
    return text_value


def sanitize_video_observation_list(values) -> list[str]:
    if not isinstance(values, list):
        return []
    cleaned = []
    for value in values:
        if value is None:
            continue
        cleaned_value = sanitize_video_observation_text(str(value))
        if cleaned_value:
            cleaned.append(cleaned_value)
    return cleaned


def base_response_video_observations(response: dict) -> dict:
    transcript = response.get("transcript") or ""
    return {
        "face_visible_percentage": None,
        "speaking_time_seconds": None,
        "filler_word_count": count_filler_words(transcript),
        "long_pause_count": None,
        "longest_pause_seconds": None,
        "response_completed_within_limit": True,
        "screen_direction_percentage": None,
        "notes": [],
    }


def build_unavailable_video_analysis(
    reason: str,
    responses: list[dict],
    status: str = "unavailable",
    video_available: bool = False,
) -> dict:
    per_response = [
        {
            "question_index": response.get("question_index"),
            "question": response.get("question"),
            "transcript": response.get("transcript"),
            "video_observations": base_response_video_observations(response),
        }
        for response in responses
    ]
    filler_total = sum(item["video_observations"].get("filler_word_count") or 0 for item in per_response)
    safe_reason = sanitize_video_observation_text(reason)
    return {
        "video_analysis_status": status if status in VIDEO_ANALYSIS_STATUSES else "unavailable",
        "video_observations": {
            "recording_quality": {
                "video_available": video_available,
                "audio_available": any((response.get("transcript") or "").strip() for response in responses),
                "face_visible_percentage": None,
                "multiple_faces_detected": None,
                "lighting": "unknown",
                "framing": "unknown",
                "audio_clarity": "unknown",
                "background_noise": "unknown",
            },
            "delivery_observations": {
                "speaking_time_seconds": None,
                "estimated_words_per_minute": None,
                "filler_word_count": filler_total,
                "long_pause_count": None,
                "longest_pause_seconds": None,
                "response_completed_within_limit": True if responses else None,
                "screen_direction_percentage": None,
            },
            "technical_observations": [safe_reason] if safe_reason else [],
            "neutral_summary": safe_reason or "Video observations are not available.",
        },
        "per_response_observations": per_response,
    }


def normalize_video_analysis_payload(raw_analysis: dict, responses: list[dict]) -> dict:
    raw_analysis = raw_analysis if isinstance(raw_analysis, dict) else {}
    raw_observations = raw_analysis.get("video_observations") or {}
    raw_quality = raw_observations.get("recording_quality") or {}
    raw_delivery = raw_observations.get("delivery_observations") or {}
    raw_per_response = raw_analysis.get("per_response_observations") or []

    response_defaults = {
        response.get("question_index"): base_response_video_observations(response)
        for response in responses
    }
    response_lookup = {
        response.get("question_index"): response
        for response in responses
    }

    per_response = []
    for response in responses:
        question_index = response.get("question_index")
        raw_item = next(
            (
                item for item in raw_per_response
                if isinstance(item, dict) and item.get("question_index") == question_index
            ),
            {},
        )
        raw_video = raw_item.get("video_observations") if isinstance(raw_item, dict) else {}
        raw_video = raw_video or {}
        defaults = response_defaults.get(question_index) or base_response_video_observations(response)
        video_observations = {
            "face_visible_percentage": clamp_percentage(raw_video.get("face_visible_percentage")),
            "speaking_time_seconds": optional_number(raw_video.get("speaking_time_seconds")),
            "filler_word_count": optional_int(raw_video.get("filler_word_count")) if raw_video.get("filler_word_count") is not None else defaults["filler_word_count"],
            "long_pause_count": optional_int(raw_video.get("long_pause_count")),
            "longest_pause_seconds": optional_number(raw_video.get("longest_pause_seconds")),
            "response_completed_within_limit": raw_video.get("response_completed_within_limit") if isinstance(raw_video.get("response_completed_within_limit"), bool) else True,
            "screen_direction_percentage": clamp_percentage(raw_video.get("screen_direction_percentage")),
            "notes": sanitize_video_observation_list(raw_video.get("notes")),
        }
        per_response.append({
            "question_index": question_index,
            "question": response_lookup.get(question_index, {}).get("question"),
            "transcript": response_lookup.get(question_index, {}).get("transcript"),
            "video_observations": video_observations,
        })

    filler_total = sum(item["video_observations"].get("filler_word_count") or 0 for item in per_response)
    return {
        "video_analysis_status": "completed",
        "video_observations": {
            "recording_quality": {
                # This normalizer is reached only after stored frames were supplied
                # to the vision analysis, so model output cannot mark video absent.
                "video_available": True,
                "audio_available": bool(raw_quality.get("audio_available", any((r.get("transcript") or "").strip() for r in responses))),
                "face_visible_percentage": clamp_percentage(raw_quality.get("face_visible_percentage")),
                "multiple_faces_detected": raw_quality.get("multiple_faces_detected") if isinstance(raw_quality.get("multiple_faces_detected"), bool) else None,
                "lighting": safe_quality(raw_quality.get("lighting")),
                "framing": safe_quality(raw_quality.get("framing")),
                "audio_clarity": safe_quality(raw_quality.get("audio_clarity")),
                "background_noise": safe_noise(raw_quality.get("background_noise")),
            },
            "delivery_observations": {
                "speaking_time_seconds": optional_number(raw_delivery.get("speaking_time_seconds")),
                "estimated_words_per_minute": optional_int(raw_delivery.get("estimated_words_per_minute")),
                "filler_word_count": optional_int(raw_delivery.get("filler_word_count")) if raw_delivery.get("filler_word_count") is not None else filler_total,
                "long_pause_count": optional_int(raw_delivery.get("long_pause_count")),
                "longest_pause_seconds": optional_number(raw_delivery.get("longest_pause_seconds")),
                "response_completed_within_limit": raw_delivery.get("response_completed_within_limit") if isinstance(raw_delivery.get("response_completed_within_limit"), bool) else True,
                "screen_direction_percentage": clamp_percentage(raw_delivery.get("screen_direction_percentage")),
            },
            "technical_observations": sanitize_video_observation_list(raw_observations.get("technical_observations")),
            "neutral_summary": sanitize_video_observation_text(raw_observations.get("neutral_summary") or "Video observations completed."),
        },
        "per_response_observations": per_response,
    }


def apply_video_observations_to_responses(responses: list[dict], video_analysis: dict) -> list[dict]:
    observations_by_index = {
        item.get("question_index"): item.get("video_observations")
        for item in video_analysis.get("per_response_observations", [])
        if isinstance(item, dict)
    }
    updated = []
    for response in responses:
        next_response = dict(response)
        next_response["video_observations"] = observations_by_index.get(
            response.get("question_index"),
            base_response_video_observations(response),
        )
        updated.append(next_response)
    return updated


def merge_recording_observations(
    video_analysis: dict,
    responses: list[dict],
    observations_by_question: dict[int, dict],
) -> dict:
    """Add deterministic measurements without touching assessment or score fields."""
    merged = dict(video_analysis or {})
    merged["observation_schema_version"] = OBSERVATION_SCHEMA_VERSION
    per_response = [dict(item) for item in merged.get("per_response_observations", [])]
    per_lookup = {
        item.get("question_index"): item for item in per_response if isinstance(item, dict)
    }
    all_heads = []
    all_speakers = []
    for response in responses:
        question_index = response.get("question_index")
        item = per_lookup.get(question_index)
        if item is None:
            item = {
                "question_index": question_index,
                "question": response.get("question"),
                "transcript": response.get("transcript"),
                "video_observations": base_response_video_observations(response),
            }
            per_response.append(item)
        item["video_observations"] = dict(item.get("video_observations") or {})
        recording = observations_by_question.get(question_index) or unavailable_recording_observations(
            "no_recording", "No recording was available for presentation or speaker observations."
        )
        head = recording.get("head_orientation") or {}
        speaker = recording.get("speaker_observations") or {}
        sampled_frames = int(head.get("sampled_frame_count") or 0)
        valid_face_frames = int(head.get("valid_face_frame_count") or 0)
        if head.get("status") == "completed" and sampled_frames:
            item["video_observations"]["face_visible_percentage"] = round(
                valid_face_frames / sampled_frames * 100,
                1,
            )
        item["video_observations"]["head_orientation"] = head
        item["video_observations"]["speaker_observations"] = speaker
        all_heads.append(head)
        all_speakers.append(speaker)

    total_sampled = sum(int(item.get("sampled_frame_count") or 0) for item in all_heads)
    total_valid = sum(int(item.get("valid_face_frame_count") or 0) for item in all_heads)
    coverage = round(total_valid / total_sampled * 100, 1) if total_sampled else None
    sustained_questions = sum(1 for item in all_heads if item.get("sustained_downward_observed"))
    additional_questions = sum(1 for item in all_speakers if item.get("possible_additional_speaker"))
    overlap_seconds = round(sum(float(item.get("overlapping_speech_seconds") or 0) for item in all_speakers), 1)
    completed_heads = sum(1 for item in all_heads if item.get("status") == "completed")
    completed_speakers = sum(1 for item in all_speakers if item.get("status") == "completed")
    summary_parts = []
    if coverage is not None:
        summary_parts.append(f"A clear face was detected in {coverage:g}% of deterministically sampled frames.")
    else:
        summary_parts.append("Clear-face coverage could not be measured from the available recordings.")
    summary_parts.append(
        f"Sustained downward head orientation met the configured threshold in {sustained_questions} response{'s' if sustained_questions != 1 else ''}."
    )
    summary_parts.append(
        f"A possible additional voice was flagged in {additional_questions} response{'s' if additional_questions != 1 else ''}."
    )
    if overlap_seconds:
        summary_parts.append(f"Possible overlapping speech totalled approximately {overlap_seconds:g} seconds.")
    summary_parts.append("These measurements describe the recording only and require recruiter review alongside playback.")
    environment = {
        "status": "completed" if completed_heads or completed_speakers else "insufficient_data",
        "responses_analysed": len(responses),
        "head_responses_completed": completed_heads,
        "speaker_responses_completed": completed_speakers,
        "face_detection_coverage_percent": coverage,
        "responses_with_sustained_downward_orientation": sustained_questions,
        "responses_with_possible_additional_speaker": additional_questions,
        "overlapping_speech_seconds": overlap_seconds,
        "neutral_summary": " ".join(summary_parts),
        "assistive_context_notice": (
            "Presentation and speaker observations are assistive context only. They do not determine honesty, "
            "personality, emotional state, protected characteristics, or candidate suitability. Recruiters must "
            "review the underlying recording and make the final decision."
        ),
    }
    overall = dict(merged.get("video_observations") or {})
    overall["environment_observations"] = environment
    quality = dict(overall.get("recording_quality") or {})
    if coverage is not None:
        quality["face_visible_percentage"] = coverage
    if any(item.get("multiple_faces_detected") is True for item in all_heads):
        quality["multiple_faces_detected"] = True
    elif all_heads and completed_heads == len(all_heads):
        quality["multiple_faces_detected"] = False
    overall["recording_quality"] = quality
    merged["video_observations"] = overall
    merged["per_response_observations"] = per_response
    return merged


@app.post("/interviews/{token}/assess-video")
async def assess_interview_with_video(token: str):
    """
    Full assessment including answer quality, safe video observations, and CV consistency.
    Video observations are assistive only and never change recruitment status or score.
    """
    interview = await interviews_collection.find_one({"token": token})
    if not interview:
        raise HTTPException(404, "Interview not found")
    if interview["status"] not in ("Completed", "Assessed"):
        raise HTTPException(400, "Interview not yet completed")

    if interview.get("video_analysis_status") == "processing":
        return {
            "message": "Video observations are still processing",
            "assessment": interview.get("assessment"),
            "video_analysis": interview.get("video_analysis"),
            "video_analysis_status": "processing",
            "cv_consistency": interview.get("cv_consistency"),
        }

    responses = backfill_missing_video_frames(interview.get("responses", []))
    stored_has_frames = any(response.get("frames_b64") for response in responses)
    stale_failed_or_unavailable_with_frames = (
        interview.get("video_analysis_status") in ("failed", "unavailable")
        and stored_has_frames
    )
    stale_observation_schema = (
        (interview.get("video_analysis") or {}).get("observation_schema_version")
        != OBSERVATION_SCHEMA_VERSION
    )

    if (
        interview.get("assessment")
        and interview.get("video_analysis_status") in ("completed", "failed", "unavailable")
        and not stale_failed_or_unavailable_with_frames
        and not stale_observation_schema
    ):
        return {
            "message": "Already assessed",
            "assessment": interview.get("assessment"),
            "video_analysis": interview.get("video_analysis"),
            "video_analysis_status": interview.get("video_analysis_status"),
            "cv_consistency": interview.get("cv_consistency"),
        }

    await interviews_collection.update_one(
        {"token": token},
        {"$set": {"video_analysis_status": "processing"}}
    )

    job = await jobs_collection.find_one({"_id": interview["job_id"]})
    candidate = await candidates_collection.find_one({"_id": interview["candidate_id"]})
    qa_text = "\n\n".join([
        f"Q{i+1}: {r['question']}\nA: {r.get('transcript', '')}"
        for i, r in enumerate(responses)
    ])

    recording_observations_by_question = {}
    observation_timing_totals = {
        "ffmpeg_seconds": 0.0,
        "head_analysis_seconds": 0.0,
        "speaker_model_load_seconds": 0.0,
        "speaker_inference_seconds": 0.0,
        "analysis_total_seconds": 0.0,
    }
    for response in responses:
        question_index = response.get("question_index")
        recording_path = resolve_stored_interview_video_path(response)
        observation_started = datetime.now(timezone.utc)
        if not recording_path or not recording_path.is_file():
            recording_observations = unavailable_recording_observations(
                "no_recording",
                "No stored recording was available for presentation or speaker observations.",
            )
        else:
            try:
                recording_observations = analyze_recording(str(recording_path))
            except Exception as observation_error:
                print(
                    "[recording observations] failed "
                    f"interview_id={interview['_id']} q={question_index} "
                    f"error_type={type(observation_error).__name__}"
                )
                recording_observations = unavailable_recording_observations(
                    "failed",
                    "Optional presentation and speaker analysis failed; transcript, score, and playback remain available.",
                )
        observation_timing = recording_observations.pop("_timing", {})
        for timing_name in observation_timing_totals:
            observation_timing_totals[timing_name] += float(
                observation_timing.get(timing_name, 0.0) or 0.0
            )
        recording_observations_by_question[question_index] = recording_observations
        head = recording_observations.get("head_orientation") or {}
        speaker = recording_observations.get("speaker_observations") or {}
        elapsed = (datetime.now(timezone.utc) - observation_started).total_seconds()
        print(
            "[recording observations] "
            f"interview_id={interview['_id']} q={question_index} "
            f"sampled_frames={head.get('sampled_frame_count', 0)} "
            f"valid_face_frames={head.get('valid_face_frame_count', 0)} "
            f"head_status={head.get('status')} speaker_status={speaker.get('status')} "
            f"analysis_seconds={elapsed:.2f}"
        )

    assessment = interview.get("assessment")
    if not assessment:
        quality_prompt = f"""You are an experienced recruitment interviewer reviewing a candidate's responses.

Job: {interview['job_title']}
Required skills: {', '.join((job or {}).get('required_skills', []))}
Candidate: {interview['candidate_name']}
Interview format: 30 seconds per answer.

Interview transcript:
{qa_text}

Assess answer relevance and evidence objectively. Do not make a hiring decision. Do not infer personality, emotions, honesty, protected characteristics, or cultural fit. Present job-relevant facts only.

Return ONLY valid JSON:
{{
  "overall_interview_score": <0-100>,
  "summary": "2-3 sentence factual summary of the answers",
  "answer_assessments": [
    {{"question_index": 0, "question": "...", "score": <0-100>, "comment": "one sentence factual answer feedback"}}
  ],
  "key_observations": ["job-relevant observation 1", "job-relevant observation 2"],
  "areas_to_probe": ["follow-up area 1", "follow-up area 2"]
}}"""

        quality_response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": quality_prompt}],
            temperature=0.3,
        )
        assessment = json.loads(strip_json_fences(quality_response.choices[0].message.content))

    all_frame_items = []
    for response in responses:
        frames = response.get("frames_b64", [])[:2]
        for frame in frames:
            if len(all_frame_items) >= 12:
                break
            all_frame_items.append({
                "question_index": response.get("question_index"),
                "question": response.get("question"),
                "transcript": response.get("transcript", ""),
                "frame": frame,
            })
        if len(all_frame_items) >= 12:
            break

    any_video_uploaded = any(response_has_video(response) for response in responses)

    if not all_frame_items:
        missing_frames_reason = (
            "Video recorded, but visual frame analysis failed."
            if any_video_uploaded
            else "No sampled video frames were available for neutral presentation observations."
        )
        video_analysis = build_unavailable_video_analysis(
            missing_frames_reason,
            responses,
            status="failed" if any_video_uploaded else "unavailable",
            video_available=any_video_uploaded,
        )
    else:
        content = [
            {
                "type": "text",
                "text": f"""You are reviewing sampled frames from a recorded 30-second-per-question video interview.

Candidate: {interview['candidate_name']}
Role: {interview['job_title']}
Responses: {len(responses)}

SAFETY RULES:
- Report only directly observable recording, delivery, and technical signals.
- Do not infer or mention honesty, deception, personality, intelligence, emotion, mental health, internal confidence, nervousness, anxiety, cultural fit, trustworthiness, enthusiasm, protected traits, or suitability for employment based on appearance.
- Do not use facial-expression emotion recognition.
- Do not create a behaviour score.
- Do not include video observations in hiring recommendations.
- Use neutral language and supporting evidence.

Allowed observations include face visibility, multiple faces, moving out of frame, framing, lighting, background noise if evident, visible interruptions or technical issues, approximate screen direction, whether the answer appears relevant based on transcript, and transcript-derived filler words.
Use null or "unknown" when a value cannot be measured reliably.

Transcript by question:
{qa_text}

Return ONLY valid JSON in this exact shape:
{{
  "video_analysis_status": "completed",
  "video_observations": {{
    "recording_quality": {{
      "video_available": true,
      "audio_available": true,
      "face_visible_percentage": <0-100 or null>,
      "multiple_faces_detected": <true|false|null>,
      "lighting": "good | acceptable | poor | unknown",
      "framing": "good | acceptable | poor | unknown",
      "audio_clarity": "good | acceptable | poor | unknown",
      "background_noise": "low | moderate | high | unknown"
    }},
    "delivery_observations": {{
      "speaking_time_seconds": <number or null>,
      "estimated_words_per_minute": <number or null>,
      "filler_word_count": <number or null>,
      "long_pause_count": <number or null>,
      "longest_pause_seconds": <number or null>,
      "response_completed_within_limit": <true|false|null>,
      "screen_direction_percentage": <0-100 or null>
    }},
    "technical_observations": ["neutral observable note"],
    "neutral_summary": "neutral factual summary"
  }},
  "per_response_observations": [
    {{
      "question_index": 0,
      "video_observations": {{
        "face_visible_percentage": <0-100 or null>,
        "speaking_time_seconds": <number or null>,
        "filler_word_count": <number or null>,
        "long_pause_count": <number or null>,
        "longest_pause_seconds": <number or null>,
        "response_completed_within_limit": true,
        "screen_direction_percentage": <0-100 or null>,
        "notes": ["neutral observable note"]
      }}
    }}
  ]
}}""",
            }
        ]

        for item in all_frame_items:
            content.append({
                "type": "text",
                "text": f"Question {item['question_index'] + 1}: {item['question']}\nTranscript: {item['transcript'][:500]}",
            })
            content.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/jpeg;base64,{item['frame']}",
                    "detail": "low",
                },
            })

        try:
            vision_response = client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": content}],
                max_tokens=900,
                temperature=0.1,
            )
            raw_video_analysis = json.loads(strip_json_fences(vision_response.choices[0].message.content))
            video_analysis = normalize_video_analysis_payload(raw_video_analysis, responses)
        except Exception as e:
            print(f"[video analysis] Failed: {e}")
            video_analysis = build_unavailable_video_analysis(
                "Video recorded, but visual frame analysis failed.",
                responses,
                status="failed",
                video_available=any_video_uploaded,
            )

    video_analysis = merge_recording_observations(
        video_analysis,
        responses,
        recording_observations_by_question,
    )
    resulting_video_status = video_analysis.get("video_analysis_status")
    for response in responses:
        print(
            "[video analysis] "
            f"interview_id={interview['_id']} "
            f"q={response.get('question_index')} "
            f"storage_key={response.get('video_storage_key')} "
            f"bytes={response.get('video_size_bytes')} "
            f"duration_seconds={response.get('video_duration_seconds')} "
            f"frames={len(response.get('frames_b64') or [])} "
            f"status={resulting_video_status}"
        )

    updated_responses = apply_video_observations_to_responses(responses, video_analysis)

    cv_consistency = interview.get("cv_consistency")
    if not cv_consistency:
        cv_raw = candidate.get("cv_raw", "") if candidate else ""
        cand_skills = candidate.get("skills", []) if candidate else []
        cand_years = candidate.get("years_experience", 0) if candidate else 0
        cand_summary = candidate.get("summary", "") if candidate else ""

        consistency_prompt = f"""You are checking whether a candidate's interview answers
are consistent with their CV claims.

CV SUMMARY: {cand_summary}
CV SKILLS: {', '.join(cand_skills)}
CV YEARS EXPERIENCE: {cand_years}
CV EXCERPT (first 2000 chars): {cv_raw[:2000]}

INTERVIEW TRANSCRIPT:
{qa_text}

Compare what the candidate said in the interview against what their CV claims.
Look for:
- Skills they claimed on CV but could not demonstrate knowledge of in the interview
- Experience levels that appear inconsistent based on answer evidence
- Specific projects or roles mentioned in CV that were contradicted in interview
- Positive consistency: CV claims they supported in their answers

IMPORTANT: Be fair and balanced. A candidate may not mention everything from their CV
in a short interview. Only flag genuine inconsistencies, not omissions.
Do not accuse - present observations factually.

Return ONLY valid JSON:
{{
  "overall_consistency_score": <0-100>,
  "consistency_summary": "2-3 sentence factual summary of CV-interview alignment",
  "verified_claims": [
    {{
      "cv_claim": "what the CV says",
      "evidence": "what the candidate said that supports this",
      "confidence": "high | medium | low"
    }}
  ],
  "inconsistencies": [
    {{
      "cv_claim": "what the CV claims",
      "interview_evidence": "what the candidate actually said",
      "severity": "minor | moderate | significant",
      "note": "brief factual observation"
    }}
  ]
}}"""

        try:
            consistency_response = client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": consistency_prompt}],
                temperature=0.2,
            )
            cv_consistency = json.loads(strip_json_fences(consistency_response.choices[0].message.content))
        except Exception as e:
            print(f"[cv consistency] Failed: {e}")
            cv_consistency = {"error": "CV consistency check could not be completed"}

    now = datetime.now(timezone.utc)
    persistence_started = time.monotonic()
    await interviews_collection.update_one(
        {"token": token},
        {"$set": {
            "responses": updated_responses,
            "assessment": assessment,
            "video_analysis": video_analysis,
            "video_analysis_status": video_analysis.get("video_analysis_status", "completed"),
            "cv_consistency": cv_consistency,
            "status": "Assessed",
            "assessed_at": now.isoformat(),
        }}
    )

    await matches_collection.update_one(
        {"_id": interview["match_id"]},
        {"$set": {"status": "Interview Completed", "updated_at": now}}
    )
    persistence_seconds = time.monotonic() - persistence_started
    observation_total_seconds = (
        observation_timing_totals["analysis_total_seconds"] + persistence_seconds
    )
    print(
        "[recording observations timing] "
        f"interview_id={interview['_id']} responses={len(responses)} "
        f"ffmpeg_seconds={observation_timing_totals['ffmpeg_seconds']:.3f} "
        f"head_analysis_seconds={observation_timing_totals['head_analysis_seconds']:.3f} "
        f"speaker_model_load_seconds={observation_timing_totals['speaker_model_load_seconds']:.3f} "
        f"speaker_inference_seconds={observation_timing_totals['speaker_inference_seconds']:.3f} "
        f"persistence_seconds={persistence_seconds:.3f} "
        f"total_seconds={observation_total_seconds:.3f}"
    )

    return {
        "message": "Full assessment complete",
        "assessment": assessment,
        "video_analysis": video_analysis,
        "video_analysis_status": video_analysis.get("video_analysis_status", "completed"),
        "cv_consistency": cv_consistency,
    }


@app.post("/interviews/{token}/assess")
async def assess_interview(token: str):
    """
    Called after all questions answered.
    GPT evaluates transcripts against job requirements.
    Updates match status to Interview Completed.
    """
    interview = await interviews_collection.find_one({"token": token})
    if not interview:
        raise HTTPException(404, "Interview not found")
    if interview["status"] not in ("Completed", "Assessed"):
        raise HTTPException(400, "Interview not yet completed")
    if interview.get("assessment"):
        return {"message": "Already assessed", "assessment": interview["assessment"]}

    job = await jobs_collection.find_one({"_id": interview["job_id"]})
    responses = interview.get("responses", [])

    qa_text = "\n\n".join([
        f"Q{i+1}: {r['question']}\nA: {r['transcript']}"
        for i, r in enumerate(responses)
    ])

    prompt = f"""You are an experienced recruitment interviewer reviewing a candidate's responses.

Job: {interview['job_title']}
Required skills: {', '.join((job or {}).get('required_skills', []))}
Candidate: {interview['candidate_name']}

Interview transcript:
{qa_text}

Assess the responses objectively. Do not make a hiring decision - present facts only.

Return ONLY valid JSON:
{{
  "overall_interview_score": <0-100>,
  "summary": "2-3 sentence factual summary of how the candidate performed",
  "answer_assessments": [
    {{
      "question_index": 0,
      "question": "...",
      "score": <0-100>,
      "comment": "one sentence factual observation"
    }}
  ],
  "key_observations": ["observation 1", "observation 2", "observation 3"],
  "areas_to_probe": ["follow-up area 1", "follow-up area 2"]
}}"""

    gpt_response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
    )
    assessment = json.loads(gpt_response.choices[0].message.content)

    now = datetime.now(timezone.utc)
    await interviews_collection.update_one(
        {"token": token},
        {"$set": {
            "assessment": assessment,
            "status": "Assessed",
            "assessed_at": now.isoformat(),
        }}
    )
    await matches_collection.update_one(
        {"_id": interview["match_id"]},
        {"$set": {"status": "Interview Completed", "updated_at": now}}
    )

    return {"message": "Assessment complete", "assessment": assessment}

#________________________________________________________

@app.get("/")
async def root():
    return {"status": "Recruitment AI API is running"}


class UpliftProfileUpdate(BaseModel):
    uplifted_profile: dict
    confirm_factual_accuracy: bool = False


def _iso(value):
    return value.isoformat() if isinstance(value, datetime) else value


def _profile_response(profile: dict) -> dict:
    generated_key = profile.get("generated_file_reference")
    original = profile.get("original_cv_reference") or {}
    return {
        "profile_id": str(profile["_id"]),
        "candidate_id": str(profile["candidate_id"]),
        "match_id": str(profile["match_id"]),
        "job_id": str(profile["job_id"]),
        "interview_id": str(profile["interview_id"]) if profile.get("interview_id") else None,
        "candidate_name": profile.get("candidate_name"),
        "target_job": profile.get("target_job"),
        "workflow_status": profile.get("workflow_status", "Uplifted"),
        "uplift_status": profile.get("uplift_status", "Ready"),
        "profile_match_score": profile.get("profile_match_score"),
        "interview_score": profile.get("interview_score"),
        "combined_score": profile.get("combined_score"),
        "original_cv_reference": {
            "source_file": original.get("source_file"),
            "available": bool(original.get("available")),
            "download_url": (
                f"/profile-uplifting/{profile['match_id']}/original"
                if original.get("available")
                else None
            ),
        },
        "uplifted_profile": profile.get("uplifted_profile") or {},
        "generated_file_reference": generated_key,
        "download_url": (
            f"/profile-uplifting/{profile['match_id']}/download"
            if generated_key
            else None
        ),
        "verified_by_recruiter_at": _iso(profile.get("verified_by_recruiter_at")),
        "created_at": _iso(profile.get("created_at")),
        "updated_at": _iso(profile.get("updated_at")),
        "generated_at": _iso(profile.get("generated_at")),
    }


def _initial_uplift_profile(candidate: dict) -> dict:
    experience = candidate.get("work_experience") or []
    current_role = next((role for role in experience if role.get("is_current")), None)
    current_role = current_role or (experience[0] if experience else {})
    skills = [str(skill).strip() for skill in candidate.get("skills", []) if str(skill).strip()]
    return {
        "name": candidate.get("name") or "",
        "professional_title": current_role.get("title") or "",
        "professional_summary": candidate.get("summary") or "",
        "core_skills": skills[:8],
        "technical_skills": skills[8:],
        "professional_experience": experience,
        "key_achievements": candidate.get("key_achievements") or [],
        "education": candidate.get("education") or [],
        "certifications": candidate.get("certifications") or [],
        "contact": {
            "email": candidate.get("email") or "",
            "phone": candidate.get("phone") or "",
            "location": candidate.get("location") or "",
        },
        "additional_information": {
            "work_rights": candidate.get("work_rights") or "",
            "notice_period": candidate.get("notice_period") or "",
        },
        "section_visibility": {
            "contact": True,
            "summary": True,
            "skills": True,
            "experience": True,
            "achievements": True,
            "education": True,
            "certifications": True,
            "additional": True,
        },
    }


@app.post("/profile-uplifting/{match_id}/prepare", dependencies=[Depends(get_current_recruiter)])
async def prepare_profile_uplift(match_id: str):
    """Idempotently initialise a verified-data profile after recruiter approval."""
    if not ObjectId.is_valid(match_id):
        raise HTTPException(404, "Match not found")
    match_object_id = ObjectId(match_id)
    match = await matches_collection.find_one({"_id": match_object_id})
    if not match:
        raise HTTPException(404, "Match not found")
    if match.get("status") not in {"Interview Completed", "Uplifted"}:
        raise HTTPException(400, "Candidate must complete recruiter-reviewed interview assessment before profile uplifting")

    existing_profile = await generated_profiles_collection.find_one({"match_id": match_object_id})
    if existing_profile:
        if match.get("status") != "Uplifted":
            await matches_collection.update_one(
                {"_id": match_object_id},
                {"$set": {"status": "Uplifted", "updated_at": datetime.now(timezone.utc)}},
            )
        return _profile_response(existing_profile)

    candidate = await candidates_collection.find_one({"_id": match["candidate_id"]})
    job = await jobs_collection.find_one({"_id": match["job_id"]})
    if not candidate:
        raise HTTPException(404, "Candidate not found")
    if not job:
        raise HTTPException(404, "Job not found")
    if not (candidate.get("cv_raw") or candidate.get("work_experience") or candidate.get("summary")):
        raise HTTPException(400, "Parsed candidate CV data is unavailable")

    interview = await interviews_collection.find_one({"match_id": match_object_id})
    assessment = (interview or {}).get("assessment") or {}
    profile_score = round(float(match.get("match_score", 0)) * 100)
    interview_score = assessment.get("overall_interview_score")
    combined_score = (
        round(profile_score * 0.6 + float(interview_score) * 0.4)
        if isinstance(interview_score, (int, float))
        else None
    )
    original_key = candidate.get("original_cv_storage_key")
    original_path = resolve_candidate_cv_storage_key(original_key) if original_key else None
    original_available = bool(original_path and original_path.is_file())
    now = datetime.now(timezone.utc)
    new_profile = {
        "candidate_id": candidate["_id"],
        "match_id": match_object_id,
        "job_id": job["_id"],
        "interview_id": interview.get("_id") if interview else None,
        "candidate_name": candidate.get("name") or "Unknown candidate",
        "target_job": job.get("title") or "Unknown role",
        "workflow_status": "Uplifted",
        "uplift_status": "Ready",
        "profile_match_score": profile_score,
        "interview_score": interview_score,
        "combined_score": combined_score,
        "original_cv_reference": {
            "source_file": candidate.get("source_file"),
            "storage_key": original_key,
            "available": original_available,
        },
        "source_snapshot": {
            "content_hash": candidate.get("content_hash"),
            "cv_raw_hash": hashlib.sha256((candidate.get("cv_raw") or "").encode("utf-8")).hexdigest(),
        },
        "uplifted_profile": _initial_uplift_profile(candidate),
        "generated_file_reference": None,
        "created_at": now,
        "updated_at": now,
    }

    try:
        await generated_profiles_collection.update_one(
            {"match_id": match_object_id},
            {"$setOnInsert": new_profile},
            upsert=True,
        )
    except DuplicateKeyError:
        pass
    await matches_collection.update_one(
        {"_id": match_object_id},
        {"$set": {"status": "Uplifted", "updated_at": now}},
    )
    profile = await generated_profiles_collection.find_one({"match_id": match_object_id})
    return _profile_response(profile)


@app.get("/profile-uplifting", dependencies=[Depends(get_current_recruiter)])
async def list_profile_uplifts():
    profiles = await generated_profiles_collection.find().sort("updated_at", -1).to_list(length=None)
    return {"profiles": [_profile_response(profile) for profile in profiles]}


@app.get("/profile-uplifting/{match_id}", dependencies=[Depends(get_current_recruiter)])
async def get_profile_uplift(match_id: str):
    if not ObjectId.is_valid(match_id):
        raise HTTPException(404, "Profile not found")
    profile = await generated_profiles_collection.find_one({"match_id": ObjectId(match_id)})
    if not profile:
        raise HTTPException(404, "Profile not found")
    return _profile_response(profile)


@app.put("/profile-uplifting/{match_id}", dependencies=[Depends(get_current_recruiter)])
async def update_profile_uplift(match_id: str, body: UpliftProfileUpdate):
    if not ObjectId.is_valid(match_id):
        raise HTTPException(404, "Profile not found")
    if not body.confirm_factual_accuracy:
        raise HTTPException(400, "Recruiter confirmation is required before saving CV edits")
    match_object_id = ObjectId(match_id)
    existing = await generated_profiles_collection.find_one({"match_id": match_object_id})
    if not existing:
        raise HTTPException(404, "Profile not found")

    current = existing.get("uplifted_profile") or {}
    allowed = {
        "professional_title",
        "professional_summary",
        "core_skills",
        "technical_skills",
        "professional_experience",
        "key_achievements",
        "education",
        "certifications",
        "section_visibility",
    }
    updated = dict(current)
    for key in allowed:
        if key in body.uplifted_profile:
            updated[key] = body.uplifted_profile[key]
    if "section_visibility" in body.uplifted_profile:
        updated["section_visibility"] = {
            **(current.get("section_visibility") or {}),
            **(body.uplifted_profile.get("section_visibility") or {}),
        }

    now = datetime.now(timezone.utc)
    await generated_profiles_collection.update_one(
        {"match_id": match_object_id},
        {
            "$set": {
                "uplifted_profile": updated,
                "uplift_status": "Draft",
                "verified_by_recruiter_at": now,
                "updated_at": now,
                "generated_file_reference": None,
            },
            "$unset": {"generated_at": ""},
        },
    )
    profile = await generated_profiles_collection.find_one({"match_id": match_object_id})
    return _profile_response(profile)


@app.post("/profile-uplifting/{match_id}/generate", dependencies=[Depends(get_current_recruiter)])
async def generate_profile_uplift(match_id: str):
    if not ObjectId.is_valid(match_id):
        raise HTTPException(404, "Profile not found")
    match_object_id = ObjectId(match_id)
    profile = await generated_profiles_collection.find_one({"match_id": match_object_id})
    if not profile:
        raise HTTPException(404, "Profile not found")
    if not profile.get("verified_by_recruiter_at"):
        raise HTTPException(400, "Save and confirm factual accuracy before generating the final CV")

    storage_key = profile_pdf_storage_key(match_object_id)
    output_path = resolve_profile_pdf_storage_key(storage_key)
    if not output_path:
        raise HTTPException(500, "Could not create a safe profile output path")
    try:
        generate_profile_pdf(profile.get("uplifted_profile") or {}, output_path)
    except Exception as exc:
        print(f"[profile uplifting] PDF generation failed for {match_id}: {exc}")
        raise HTTPException(500, "Profile generation failed") from exc

    now = datetime.now(timezone.utc)
    await generated_profiles_collection.update_one(
        {"match_id": match_object_id},
        {"$set": {
            "generated_file_reference": storage_key,
            "uplift_status": "Generated",
            "generated_at": now,
            "updated_at": now,
        }},
    )
    updated = await generated_profiles_collection.find_one({"match_id": match_object_id})
    return _profile_response(updated)


@app.get("/profile-uplifting/{match_id}/download", dependencies=[Depends(get_current_recruiter)])
async def download_profile_uplift(match_id: str):
    if not ObjectId.is_valid(match_id):
        raise HTTPException(404, "Profile not found")
    profile = await generated_profiles_collection.find_one({"match_id": ObjectId(match_id)})
    if not profile:
        raise HTTPException(404, "Profile not found")
    output_path = resolve_profile_pdf_storage_key(profile.get("generated_file_reference"))
    if not output_path or not output_path.is_file():
        raise HTTPException(404, "Generated profile file is missing")
    safe_name = re.sub(r"[^A-Za-z0-9_-]+", "-", profile.get("candidate_name") or "candidate").strip("-")
    return FileResponse(output_path, media_type="application/pdf", filename=f"{safe_name}-candidate-profile.pdf")


@app.get("/profile-uplifting/{match_id}/original", dependencies=[Depends(get_current_recruiter)])
async def download_original_cv(match_id: str):
    if not ObjectId.is_valid(match_id):
        raise HTTPException(404, "Profile not found")
    profile = await generated_profiles_collection.find_one({"match_id": ObjectId(match_id)})
    if not profile:
        raise HTTPException(404, "Profile not found")
    original = profile.get("original_cv_reference") or {}
    original_path = resolve_candidate_cv_storage_key(original.get("storage_key"))
    if not original_path or not original_path.is_file():
        raise HTTPException(404, "Original CV file is unavailable for this historical candidate")
    return FileResponse(original_path, filename=original.get("source_file") or original_path.name)


@app.post("/jobs/upload", dependencies=[Depends(get_current_recruiter)])
async def upload_job(
    file: UploadFile = File(...),
    client_name: Optional[str] = Form(None),
    location: Optional[str] = Form(None),
    salary_range: Optional[str] = Form(None),
    experience_required: Optional[str] = Form(None),
):
    """
    Upload a JD file (.docx or .pdf). Parses it (may detect multiple roles),
    embeds each role, stores each as its own job document in MongoDB, and
    immediately matches each new role against every existing candidate.
    """
    tmp_path, content_hash, _uploaded_bytes = await save_uploaded_file_to_temp(file)
    try:
        raw_text = load_text_file(tmp_path)
    finally:
        os.remove(tmp_path)

    if not raw_text.strip():
        raise HTTPException(400, "Could not extract text from this file — it may be a scanned/image-based PDF.")

    # Duplicate check — same file content already uploaded (even under a different filename)
    existing = await jobs_collection.find_one({"content_hash": content_hash})
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"This file has already been uploaded (originally as '{existing.get('source_file')}')."
        )

    roles = parse_jd(raw_text, file.filename)
    created_job_ids = []

    existing_candidate_count = await candidates_collection.count_documents({})
    matched_candidate_count = 0

    for role in roles:
        embed_text = build_embedding_text_from_job(role)
        embedding = get_embedding(embed_text)

        job_doc = {
            **role,
            "embedding": embedding,
            "source_file": file.filename,
            "content_hash": content_hash,
            "description_raw": raw_text,
            "client_name": client_name or "",
            "location": location or "",
            "salary_range": salary_range or "",
            "experience_required": experience_required or "",
            "status": "Open",
            "created_at": datetime.now(timezone.utc),
        }
        result = await jobs_collection.insert_one(job_doc)
        job_id = result.inserted_id
        created_job_ids.append(str(job_id))

        if VECTOR_BACKEND == "weaviate":
            await asyncio.to_thread(
                insert_job_vector, job_id, job_doc, embedding
            )

        if existing_candidate_count:
            top_candidates = await search_candidate_vectors(
                embedding, existing_candidate_count
            )
            matched_candidate_count += len(top_candidates)

            for candidate in top_candidates:
                await upsert_match(job_id, candidate["_id"], candidate.get("score", 0))
    return {
        "message": f"{len(roles)} role(s) detected and stored",
        "job_ids": created_job_ids,
        "matched_against_existing_candidates": matched_candidate_count,
    }


@app.post("/candidates/upload", dependencies=[Depends(get_current_recruiter)])
async def upload_candidate(file: UploadFile = File(...)):
    """
    Upload a CV file (.docx or .pdf). Parses it, embeds it, stores it as a
    candidate document in MongoDB, and immediately matches it against every
    existing job.
    """
    tmp_path, content_hash, original_cv_bytes = await save_uploaded_file_to_temp(file)
    try:
        raw_text = load_text_file(tmp_path)
    finally:
        os.remove(tmp_path)

    if not raw_text.strip():
        raise HTTPException(400, "Could not extract text from this file — it may be a scanned/image-based PDF.")

    # Duplicate check — same CV already uploaded
    existing = await candidates_collection.find_one({"content_hash": content_hash})
    if existing:
        raise HTTPException(
    status_code=409,
    detail=f"This file has already been uploaded (as '{existing.get('name')}', file: '{existing.get('source_file')}')."
)

    parsed = parse_cv(raw_text)
    parsed["name"] = parsed.get("name") or file.filename
    embed_text = build_embedding_text_from_candidate(parsed)
    embedding = get_embedding(embed_text)

    candidate_doc = {
        **parsed,
        "embedding": embedding,
        "source_file": file.filename,
        "content_hash": content_hash,
        "cv_raw": raw_text,
        "created_at": datetime.now(timezone.utc),
    }
    candidate_id = await persist_candidate_with_original_cv(
        candidate_doc,
        original_cv_bytes,
        file.filename,
    )

    if VECTOR_BACKEND == "weaviate":
        await asyncio.to_thread(
            insert_candidate_vector, candidate_id, candidate_doc, embedding
        )

    existing_job_count = await jobs_collection.count_documents({})
    top_jobs = []

    if existing_job_count:
        top_jobs = await search_job_vectors(embedding, existing_job_count)

        for job in top_jobs:
            await upsert_match(job["_id"], candidate_id, job.get("score", 0))

    return {
        "message": "Candidate stored and matched",
        "candidate_id": str(candidate_id),
        "matched_against_existing_jobs": len(top_jobs),
    }


@app.get("/matches/by-job/{job_id}", dependencies=[Depends(get_current_recruiter)])
async def get_matches_by_job(job_id: str):
    """Ranked list of candidates for one job, highest score first."""
    matches = await matches_collection.find({"job_id": ObjectId(job_id)}).to_list(length=None)
    if not matches:
        raise HTTPException(404, "No matches found for this job_id")

    enriched = []
    for m in matches:
        cand = await candidates_collection.find_one({"_id": m["candidate_id"]})
        enriched.append({
            "match_id": str(m["_id"]),
            "candidate_id": str(m["candidate_id"]),
            "candidate_name": cand.get("name") if cand else "Unknown",
            "candidate_email": cand.get("email") if cand else None,
            "score": m["match_score"],
            "status": m["status"],
            "status_note": m.get("status_note", ""),
            "analysis": m.get("analysis"),
            "skill_analysis": m.get("skill_analysis"),
            "analysis_generated_at": m.get("analysis_generated_at"),
        })
    enriched.sort(key=lambda x: x["score"], reverse=True)
    return {"job_id": job_id, "ranked_candidates": enriched}


@app.post("/matches/run/{job_id}", dependencies=[Depends(get_current_recruiter)])
async def run_matching_analysis(job_id: str):
    """Re-run vector matching for an existing job and persist the matches."""
    if not ObjectId.is_valid(job_id):
        raise HTTPException(400, "Invalid job id")
    object_id = ObjectId(job_id)
    job = await jobs_collection.find_one({"_id": object_id})
    if not job:
        raise HTTPException(404, "Job not found")

    persisted_matches = await match_candidates_for_job(object_id, job)
    return {"job_id": job_id, "matched_candidates": persisted_matches}


@app.get("/matches/by-candidate/{candidate_id}", dependencies=[Depends(get_current_recruiter)])
async def get_matches_by_candidate(candidate_id: str):
    """Ranked list of jobs for one candidate, best fit first."""
    matches = await matches_collection.find({"candidate_id": ObjectId(candidate_id)}).to_list(length=None)
    if not matches:
        raise HTTPException(404, "No matches found for this candidate_id")

    enriched = []
    for m in matches:
        job = await jobs_collection.find_one({"_id": m["job_id"]})
        enriched.append({
            "match_id": str(m["_id"]),
            "job_id": str(m["job_id"]),
            "job_title": job.get("title") if job else "Unknown",
            "job_domain": job.get("domain") if job else None,
            "score": m["match_score"],
            "status": m["status"],
            "status_note": m.get("status_note", ""),
            "analysis": m.get("analysis"),
            "skill_analysis": m.get("skill_analysis"),
        })
    enriched.sort(key=lambda x: x["score"], reverse=True)
    return {"candidate_id": candidate_id, "ranked_jobs": enriched}


# ---------------------------------------------------------------------------
# Status update
# ---------------------------------------------------------------------------

VALID_STATUSES = [
    "Uploaded",
    "Matched",
    "Approved",
    "Shortlisted",
    "Interview Sent",
    "Interview Completed",
    "Uplifted",
    "Sent",
]

class StatusUpdate(BaseModel):
    status: str
    status_note: Optional[str] = ""


@app.patch("/matches/{match_id}/status", dependencies=[Depends(get_current_recruiter)])
async def update_match_status(match_id: str, body: StatusUpdate):
    """
    Move a match record through the pipeline.
    Valid values: Uploaded → Matched → Approved → Shortlisted → Uplifted → Sent
    Optionally include a status_note for free-text detail
    (e.g. '3rd round to be scheduled', 'Not interested due to CTC').

    Example request body:
        { "status": "Approved", "status_note": "Client liked the profile" }
    """
    if body.status not in VALID_STATUSES:
        raise HTTPException(
            400,
            f"Invalid status '{body.status}'. Must be one of: {', '.join(VALID_STATUSES)}"
        )

    result = await matches_collection.update_one(
        {"_id": ObjectId(match_id)},
        {"$set": {
            "status": body.status,
            "status_note": body.status_note,
            "updated_at": datetime.now(timezone.utc),
        }}
    )

    if result.matched_count == 0:
        raise HTTPException(404, f"No match found with id {match_id}")

    return {
        "match_id": match_id,
        "updated_status": body.status,
        "status_note": body.status_note,
    }


@app.get("/matches/{match_id}", dependencies=[Depends(get_current_recruiter)])
async def get_match(match_id: str):
    """Get a single match record by ID including cached analysis."""
    m = await matches_collection.find_one({"_id": ObjectId(match_id)})
    if not m:
        raise HTTPException(404, f"No match found with id {match_id}")

    job = await jobs_collection.find_one({"_id": m["job_id"]})
    cand = await candidates_collection.find_one({"_id": m["candidate_id"]})

    return {
        "match_id": str(m["_id"]),
        "job_id": str(m["job_id"]),
        "candidate_id": str(m["candidate_id"]),
        "job_title": job.get("title") if job else "Unknown",
        "candidate_name": cand.get("name") if cand else "Unknown",
        "candidate_email": cand.get("email") if cand else None,
        "score": m["match_score"],
        "status": m["status"],
        "status_note": m.get("status_note", ""),
        "analysis": m.get("analysis"),
        "skill_analysis": m.get("skill_analysis"),
        "analysis_generated_at": m.get("analysis_generated_at"),
        "created_at": m.get("created_at"),
        "updated_at": m.get("updated_at"),
    }


# ---------------------------------------------------------------------------
# List endpoints — needed by the dashboard to show all jobs / candidates
# ---------------------------------------------------------------------------

@app.get("/jobs", dependencies=[Depends(get_current_recruiter)])
async def list_jobs(status: Optional[str] = None):
    """
    List all jobs stored in the database.
    Optionally filter by status: ?status=Open or ?status=Closed

    Returns lightweight job cards — title, domain, source file, status.
    Does NOT return embeddings (too large, not needed by the frontend).
    """
    query = {}
    if status:
        query["status"] = status

    jobs = await jobs_collection.find(query).to_list(length=None)
    return {
        "total": len(jobs),
        "jobs": [
            {
                "job_id": str(j["_id"]),
                "title": j.get("title"),
                "domain": j.get("domain"),
                "client": j.get("client_name") or j.get("domain") or "—",
                "client_name": j.get("client_name") or "",
                "source_file": j.get("source_file"),
                "status": j.get("status"),
                "required_skills": j.get("required_skills", []),
                "nice_to_have_skills": j.get("nice_to_have_skills", []),
                "min_years_experience": j.get("min_years_experience"),
                "summary": j.get("summary") or "",
                "location": j.get("location") or "",
                "salary_range": j.get("salary_range") or "",
                "experience_required": j.get("experience_required") or "",
                "created_at": j.get("created_at"),
            }
            for j in jobs
        ],
    }


@app.get("/candidates", dependencies=[Depends(get_current_recruiter)])
async def list_candidates():
    """
    List all candidates stored in the database.
    Returns lightweight candidate cards — name, skills, domain, work rights.
    Does NOT return embeddings or raw CV text (too large).
    """
    candidates = await candidates_collection.find().to_list(length=None)
    return {
        "total": len(candidates),
        "candidates": [
            {
                "candidate_id": str(c["_id"]),
                "name": c.get("name"),
                "email": c.get("email"),
                "phone": c.get("phone"),
                "skills": c.get("skills", []),
                "years_experience": c.get("years_experience"),
                "domain_experience": c.get("domain_experience", []),
                "work_rights": c.get("work_rights"),
                "notice_period": c.get("notice_period"),
                "source_file": c.get("source_file"),
                "summary": c.get("summary") or "",
                "key_achievements": c.get("key_achievements", []),
                "created_at": c.get("created_at"),
            }
            for c in candidates
        ],
    }


@app.get("/jobs/{job_id}", dependencies=[Depends(get_current_recruiter)])
async def get_job(job_id: str):
    """Get full details of one job by ID."""
    job = await jobs_collection.find_one({"_id": ObjectId(job_id)})
    if not job:
        raise HTTPException(404, f"No job found with id {job_id}")

    return {
        "job_id": str(job["_id"]),
        "title": job.get("title"),
        "domain": job.get("domain"),
        "client": job.get("client_name") or job.get("domain") or "—",
        "client_name": job.get("client_name") or "",
        "source_file": job.get("source_file"),
        "description_raw": job.get("description_raw"),
        "status": job.get("status"),
        "required_skills": job.get("required_skills", []),
        "nice_to_have_skills": job.get("nice_to_have_skills", []),
        "min_years_experience": job.get("min_years_experience"),
        "summary": job.get("summary") or "",
        "location": job.get("location") or "",
        "salary_range": job.get("salary_range") or "",
        "experience_required": job.get("experience_required") or "",
        "created_at": job.get("created_at"),
    }


@app.get("/candidates/{candidate_id}", dependencies=[Depends(get_current_recruiter)])
async def get_candidate(candidate_id: str):
    """Get full details of one candidate by ID."""
    cand = await candidates_collection.find_one({"_id": ObjectId(candidate_id)})
    if not cand:
        raise HTTPException(404, f"No candidate found with id {candidate_id}")

    return {
        "candidate_id": str(cand["_id"]),
        "name": cand.get("name"),
        "email": cand.get("email"),
        "phone": cand.get("phone"),
        "skills": cand.get("skills", []),
        "years_experience": cand.get("years_experience"),
        "domain_experience": cand.get("domain_experience", []),
        "work_rights": cand.get("work_rights"),
        "notice_period": cand.get("notice_period"),
        "source_file": cand.get("source_file"),
        "summary": cand.get("summary") or "",
        "work_experience": cand.get("work_experience", []),
        "education": cand.get("education", []),
        "key_achievements": cand.get("key_achievements", []),
        "created_at": cand.get("created_at"),
    }
