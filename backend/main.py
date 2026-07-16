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

import os
import json
import hashlib
import tempfile
from datetime import datetime, timezone
from typing import Optional
from bson import ObjectId

import numpy as np
from fastapi import FastAPI, UploadFile, File, HTTPException, Form
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
from db import jobs_collection, candidates_collection, matches_collection

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

CHAT_MODEL = "gpt-4o-mini"
EMBED_MODEL = "text-embedding-3-small"

app = FastAPI(title="Recruitment AI API")
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
    await deduplicate_match_documents()
    await matches_collection.create_index(
        [("job_id", 1), ("candidate_id", 1)],
        unique=True,
        name="unique_job_candidate_match",
    )


async def save_uploaded_file_to_temp(upload_file: UploadFile) -> tuple[str, str]:
    """Save an uploaded file to a temp path and return (tmp_path, content_hash).
    The hash is an MD5 of the raw file bytes — used to detect duplicate uploads
    regardless of filename. Returned alongside the path so the caller can check
    for duplicates before doing any GPT/embedding work.
    """
    suffix = os.path.splitext(upload_file.filename)[1]
    contents = await upload_file.read()
    content_hash = hashlib.md5(contents).hexdigest()
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(contents)
        return tmp.name, content_hash


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.post("/matches/{match_id}/analyse")
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
    job_years = job.get("min_years_experience") or 0
    cand_years = candidate.get("years_experience") or 0

    # Calculate skill overlap
    job_skills_lower = [s.lower() for s in job_skills]
    cand_skills_lower = [s.lower() for s in cand_skills]
    matched_skills = [s for s in job_skills if s.lower() in cand_skills_lower]
    missing_skills = [s for s in job_skills if s.lower() not in cand_skills_lower]

    # Calculate tech match %
    tech_match = round((len(matched_skills) / len(job_skills) * 100)) if job_skills else 0

    # Calculate experience match %
    if job_years == 0:
        exp_match = 100
    elif cand_years >= job_years:
        exp_match = 100
    else:
        exp_match = round((cand_years / job_years) * 100)

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
Experience Match: {exp_match}% ({cand_years} years vs {job_years} years required)

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

@app.get("/matches/{match_id}/skill-analysis")
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

    # Return cached result if already computed
    if m.get("skill_analysis"):
        return m["skill_analysis"]

    job = await jobs_collection.find_one({"_id": m["job_id"]})
    candidate = await candidates_collection.find_one({"_id": m["candidate_id"]})

    if not job or not candidate:
        raise HTTPException(404, "Job or candidate not found")

    job_skills = job.get("required_skills", [])
    cand_skills = candidate.get("skills", [])

    if not job_skills or not cand_skills:
        result = {
            "match_id": match_id,
            "semantic_skill_score": 0,
            "matched": [],
            "partial": [],
            "missing": [
                {"required": s, "similarity": 0, "type": "missing"}
                for s in job_skills
            ],
            "summary": "No skills available for comparison"
        }
        return result

    # Embed all skills in one batch call — cheaper than one call per skill
    all_skills = job_skills + cand_skills
    embed_response = client.embeddings.create(model=EMBED_MODEL, input=all_skills)
    embeddings = [r.embedding for r in embed_response.data]

    job_embeddings = embeddings[:len(job_skills)]
    cand_embeddings = embeddings[len(job_skills):]

    matched = []
    partial = []
    missing = []

    for i, job_skill in enumerate(job_skills):
        best_score = 0.0
        best_cand_skill = None

        for j, cand_skill in enumerate(cand_skills):
            score = cosine_similarity(job_embeddings[i], cand_embeddings[j])
            if score > best_score:
                best_score = score
                best_cand_skill = cand_skill

        if best_score >= 0.80:
            matched.append({
                "required": job_skill,
                "matched_with": best_cand_skill,
                "similarity": round(best_score, 3),
                "type": "strong"
            })
        elif best_score >= 0.65:
            partial.append({
                "required": job_skill,
                "closest_match": best_cand_skill,
                "similarity": round(best_score, 3),
                "type": "partial"
            })
        else:
            missing.append({
                "required": job_skill,
                "closest_match": best_cand_skill,
                "similarity": round(best_score, 3),
                "type": "missing"
            })

    semantic_score = round(
        ((len(matched) + 0.5 * len(partial)) / len(job_skills)) * 100
    ) if job_skills else 0

    result = {
        "match_id": match_id,
        "semantic_skill_score": semantic_score,
        "matched": matched,
        "partial": partial,
        "missing": missing,
        "summary": (
            f"{len(matched)} strong match(es), {len(partial)} transferable "
            f"skill(s), {len(missing)} gap(s) out of {len(job_skills)} required skills"
        )
    }

    # Cache on the match document so subsequent calls are instant
    await matches_collection.update_one(
        {"_id": ObjectId(match_id)},
        {"$set": {
            "skill_analysis": result,
            "skill_analysis_at": datetime.now(timezone.utc),
        }}
    )

    return result


#________________________________________________________

@app.get("/")
async def root():
    return {"status": "Recruitment AI API is running"}


@app.post("/jobs/upload")
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
    tmp_path, content_hash = await save_uploaded_file_to_temp(file)
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

        if existing_candidate_count:
            pipeline = build_vector_search_pipeline(embedding, existing_candidate_count)
            top_candidates = await candidates_collection.aggregate(pipeline).to_list(length=None)
            matched_candidate_count += len(top_candidates)

            for candidate in top_candidates:
                await upsert_match(job_id, candidate["_id"], candidate.get("score", 0))
    return {
        "message": f"{len(roles)} role(s) detected and stored",
        "job_ids": created_job_ids,
        "matched_against_existing_candidates": matched_candidate_count,
    }


@app.post("/candidates/upload")
async def upload_candidate(file: UploadFile = File(...)):
    """
    Upload a CV file (.docx or .pdf). Parses it, embeds it, stores it as a
    candidate document in MongoDB, and immediately matches it against every
    existing job.
    """
    tmp_path, content_hash = await save_uploaded_file_to_temp(file)
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
    result = await candidates_collection.insert_one(candidate_doc)
    candidate_id = result.inserted_id

    existing_job_count = await jobs_collection.count_documents({})
    top_jobs = []

    if existing_job_count:
        pipeline = build_vector_search_pipeline(embedding, existing_job_count)
        top_jobs = await jobs_collection.aggregate(pipeline).to_list(length=None)

        for job in top_jobs:
            await upsert_match(job["_id"], candidate_id, job.get("score", 0))

    return {
        "message": "Candidate stored and matched",
        "candidate_id": str(candidate_id),
        "matched_against_existing_jobs": len(top_jobs),
    }


@app.get("/matches/by-job/{job_id}")
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


@app.get("/matches/by-candidate/{candidate_id}")
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


@app.patch("/matches/{match_id}/status")
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


@app.get("/matches/{match_id}")
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

@app.get("/jobs")
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


@app.get("/candidates")
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


@app.get("/jobs/{job_id}")
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


@app.get("/candidates/{candidate_id}")
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
