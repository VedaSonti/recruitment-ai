"""Migrate existing MongoDB job/candidate embeddings to Weaviate.

MongoDB is read-only in this script. Existing Weaviate objects are skipped by
the deterministic-ID insert functions, so interrupted runs can be resumed.
"""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Callable
from typing import Any

from db import candidates_collection, jobs_collection, mongo_client
from weaviate_service import (
    LEGACY_COLLECTIONS,
    VECTOR_COLLECTION,
    close_weaviate,
    connect_to_weaviate,
    ensure_collections,
    insert_candidate_vector,
    insert_job_vector,
    remove_legacy_collections,
)


async def migrate_collection(
    collection,
    label: str,
    insert_vector: Callable[[Any, dict, list[float]], bool],
    *,
    dry_run: bool = False,
) -> dict[str, int]:
    counts = {"eligible": 0, "migrated": 0, "skipped": 0, "missing_vector": 0}
    cursor = collection.find({}, {"embedding": 1, "name": 1, "skills": 1,
                                  "years_experience": 1, "source_file": 1,
                                  "title": 1, "client_name": 1, "domain": 1})
    async for document in cursor:
        vector = document.get("embedding")
        if not isinstance(vector, list) or not vector:
            counts["missing_vector"] += 1
            continue

        counts["eligible"] += 1
        if dry_run:
            continue

        inserted = await asyncio.to_thread(
            insert_vector, document["_id"], document, vector
        )
        counts["migrated" if inserted else "skipped"] += 1
        processed = counts["migrated"] + counts["skipped"]
        if processed % 100 == 0:
            print(f"[{label}] processed {processed} vectors")

    return counts


async def migrate(
    *, dry_run: bool = False, replace_legacy_collections: bool = False
) -> dict[str, dict[str, int]]:
    try:
        if not dry_run:
            client = await asyncio.to_thread(connect_to_weaviate)
            legacy_present = [
                name for name in LEGACY_COLLECTIONS
                if client.collections.exists(name)
            ]
            if legacy_present:
                if not replace_legacy_collections:
                    names = ", ".join(legacy_present)
                    raise RuntimeError(
                        f"Legacy vector collection(s) exist: {names}. Re-run with "
                        "--replace-legacy-collections to rebuild them safely from MongoDB."
                    )
                removed = await asyncio.to_thread(remove_legacy_collections, client)
                print(f"[migration] removed legacy collection(s): {', '.join(removed)}")
            await asyncio.to_thread(ensure_collections, client)

        candidate_counts = await migrate_collection(
            candidates_collection,
            "candidates",
            insert_candidate_vector,
            dry_run=dry_run,
        )
        job_counts = await migrate_collection(
            jobs_collection,
            "jobs",
            insert_job_vector,
            dry_run=dry_run,
        )
    finally:
        if not dry_run:
            await asyncio.to_thread(close_weaviate)

    return {"candidates": candidate_counts, "jobs": job_counts}


def main() -> None:
    try:
        parser = argparse.ArgumentParser(
            description="Copy existing MongoDB embeddings into Weaviate"
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="count eligible MongoDB records without connecting to Weaviate",
        )
        parser.add_argument(
            "--replace-legacy-collections",
            action="store_true",
            help=(
                "delete obsolete CandidateProfile/JobProfile vector collections before "
                "rebuilding RecruitmentVector from read-only MongoDB data"
            ),
        )
        args = parser.parse_args()
        results = asyncio.run(
            migrate(
                dry_run=args.dry_run,
                replace_legacy_collections=args.replace_legacy_collections,
            )
        )
        mode = "dry-run" if args.dry_run else "migration"
        for label, counts in results.items():
            print(
                f"[{mode}] {label}: eligible={counts['eligible']} "
                f"migrated={counts['migrated']} skipped={counts['skipped']} "
                f"missing_vector={counts['missing_vector']}"
            )
    finally:
        try:
            close_weaviate()
        finally:
            mongo_client.close()


if __name__ == "__main__":
    main()
