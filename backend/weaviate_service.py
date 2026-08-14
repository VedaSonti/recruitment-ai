"""Isolated Weaviate vector storage and nearest-neighbour search.

MongoDB remains the source of truth for every business record.  This module
stores only externally generated vectors plus the minimum metadata needed to
map a Weaviate result back to its MongoDB document.
"""

from __future__ import annotations

import os
import threading
import uuid
from typing import Any, Optional

from dotenv import load_dotenv

load_dotenv()

VECTOR_COLLECTION = "RecruitmentVector"
LEGACY_COLLECTIONS = ("CandidateProfile", "JobProfile")

_client: Any = None
_client_lock = threading.Lock()


def connect_to_weaviate():
    """Return a reusable authenticated Weaviate Cloud client."""
    global _client
    if _client is not None:
        return _client

    url = os.getenv("WEAVIATE_URL")
    api_key = os.getenv("WEAVIATE_API_KEY")
    if not url or not api_key:
        raise RuntimeError(
            "WEAVIATE_URL and WEAVIATE_API_KEY are required when "
            "VECTOR_BACKEND=weaviate"
        )

    try:
        import weaviate
        from weaviate.classes.init import AdditionalConfig, Auth, Timeout
    except ImportError as exc:
        raise RuntimeError(
            "weaviate-client is required when VECTOR_BACKEND=weaviate"
        ) from exc

    with _client_lock:
        if _client is None:
            client = None
            try:
                client = weaviate.connect_to_weaviate_cloud(
                    cluster_url=url,
                    auth_credentials=Auth.api_key(api_key),
                    additional_config=AdditionalConfig(
                        timeout=Timeout(init=30, query=60, insert=120)
                    ),
                )
                if not client.is_ready():
                    raise RuntimeError("Weaviate Cloud is not ready")
                _client = client
            except Exception:
                if client is not None:
                    client.close()
                raise
    return _client


def close_weaviate() -> None:
    """Close the cached client, primarily for shutdown and tests."""
    global _client
    with _client_lock:
        client, _client = _client, None
    if client is not None:
        client.close()


def ensure_collections(client=None) -> None:
    """Create the single self-provided-vector collection when it is absent."""
    client = client or connect_to_weaviate()
    from weaviate.classes.config import Configure, DataType, Property

    if not client.collections.exists(VECTOR_COLLECTION):
        client.collections.create(
            name=VECTOR_COLLECTION,
            vector_config=Configure.Vectors.self_provided(),
            properties=[
                Property(name="entity_type", data_type=DataType.TEXT),
                Property(name="mongo_id", data_type=DataType.TEXT),
                Property(name="candidate_id", data_type=DataType.TEXT),
                Property(name="job_id", data_type=DataType.TEXT),
                Property(name="name", data_type=DataType.TEXT),
                Property(name="skills", data_type=DataType.TEXT_ARRAY),
                Property(name="experience_years", data_type=DataType.NUMBER),
                Property(name="source_file", data_type=DataType.TEXT),
                Property(name="title", data_type=DataType.TEXT),
                Property(name="client", data_type=DataType.TEXT),
            ],
        )


def remove_legacy_collections(client=None) -> list[str]:
    """Delete obsolete split vector collections during an explicit migration."""
    client = client or connect_to_weaviate()
    removed = []
    for name in LEGACY_COLLECTIONS:
        if client.collections.exists(name):
            client.collections.delete(name)
            removed.append(name)
    return removed


def mongo_object_uuid(kind: str, mongo_id: Any) -> uuid.UUID:
    """Create a stable Weaviate UUID for an object owned by MongoDB."""
    return uuid.uuid5(uuid.NAMESPACE_URL, f"recruitment-ai:{kind}:{mongo_id}")


def atlas_score_from_weaviate_distance(distance: Optional[float]) -> float:
    """Map Weaviate cosine distance onto MongoDB Atlas's 0..1 score scale.

    Weaviate cosine distance is ``1 - cosine_similarity``. Atlas normalizes
    cosine similarity as ``(1 + cosine_similarity) / 2``. Combining the two
    formulae gives ``1 - distance / 2``.
    """
    if distance is None:
        return 0.0
    return max(0.0, min(1.0, 1.0 - (float(distance) / 2.0)))


def _candidate_properties(candidate_id: Any, candidate: dict) -> dict:
    years = candidate.get("years_experience")
    return {
        "entity_type": "candidate",
        "mongo_id": str(candidate_id),
        "candidate_id": str(candidate_id),
        "name": str(candidate.get("name") or ""),
        "skills": [str(skill) for skill in candidate.get("skills", []) if skill],
        "experience_years": float(years) if isinstance(years, (int, float)) else 0.0,
        "source_file": str(candidate.get("source_file") or ""),
    }


def _job_properties(job_id: Any, job: dict) -> dict:
    return {
        "entity_type": "job",
        "mongo_id": str(job_id),
        "job_id": str(job_id),
        "title": str(job.get("title") or ""),
        "client": str(job.get("client_name") or job.get("domain") or ""),
    }


def _insert_vector(
    object_uuid: uuid.UUID,
    properties: dict,
    vector: list[float],
    client=None,
) -> bool:
    client = client or connect_to_weaviate()
    collection = client.collections.use(VECTOR_COLLECTION)
    if collection.query.fetch_object_by_id(object_uuid) is not None:
        return False
    collection.data.insert(uuid=object_uuid, properties=properties, vector=vector)
    return True


def insert_candidate_vector(
    candidate_id: Any,
    candidate: dict,
    vector: list[float],
    client=None,
) -> bool:
    return _insert_vector(
        mongo_object_uuid("candidate", candidate_id),
        _candidate_properties(candidate_id, candidate),
        vector,
        client,
    )


def update_candidate_vector(
    candidate_id: Any,
    candidate: dict,
    vector: list[float],
    client=None,
) -> None:
    client = client or connect_to_weaviate()
    client.collections.use(VECTOR_COLLECTION).data.update(
        uuid=mongo_object_uuid("candidate", candidate_id),
        properties=_candidate_properties(candidate_id, candidate),
        vector=vector,
    )


def delete_candidate_vector(candidate_id: Any, client=None) -> None:
    client = client or connect_to_weaviate()
    client.collections.use(VECTOR_COLLECTION).data.delete_by_id(
        mongo_object_uuid("candidate", candidate_id)
    )


def insert_job_vector(
    job_id: Any,
    job: dict,
    vector: list[float],
    client=None,
) -> bool:
    return _insert_vector(
        mongo_object_uuid("job", job_id),
        _job_properties(job_id, job),
        vector,
        client,
    )


def update_job_vector(
    job_id: Any,
    job: dict,
    vector: list[float],
    client=None,
) -> None:
    client = client or connect_to_weaviate()
    client.collections.use(VECTOR_COLLECTION).data.update(
        uuid=mongo_object_uuid("job", job_id),
        properties=_job_properties(job_id, job),
        vector=vector,
    )


def delete_job_vector(job_id: Any, client=None) -> None:
    client = client or connect_to_weaviate()
    client.collections.use(VECTOR_COLLECTION).data.delete_by_id(
        mongo_object_uuid("job", job_id)
    )


def _search(
    entity_type: str,
    id_property: str,
    vector: list[float],
    limit: int,
    client=None,
) -> list[dict]:
    if limit <= 0:
        return []
    client = client or connect_to_weaviate()
    from weaviate.classes.query import Filter, MetadataQuery

    response = client.collections.use(VECTOR_COLLECTION).query.near_vector(
        near_vector=vector,
        limit=limit,
        filters=Filter.by_property("entity_type").equal(entity_type),
        return_metadata=MetadataQuery(distance=True),
    )
    results = []
    for item in response.objects:
        mongo_id = item.properties.get(id_property)
        if not mongo_id:
            continue
        results.append(
            {
                id_property: str(mongo_id),
                "score": atlas_score_from_weaviate_distance(item.metadata.distance),
            }
        )
    return results


def search_candidates(vector: list[float], limit: int, client=None) -> list[dict]:
    return _search("candidate", "candidate_id", vector, limit, client)


def search_jobs(vector: list[float], limit: int, client=None) -> list[dict]:
    return _search("job", "job_id", vector, limit, client)
