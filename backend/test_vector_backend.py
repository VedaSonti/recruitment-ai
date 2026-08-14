import ast
import asyncio
import unittest
from pathlib import Path

from bson import ObjectId


class FakeAggregate:
    def __init__(self, documents):
        self.documents = documents

    async def to_list(self, length=None):
        return self.documents


class FakeFind(FakeAggregate):
    pass


class FakeCollection:
    def __init__(self, documents):
        self.documents = documents
        self.pipeline = None

    def aggregate(self, pipeline):
        self.pipeline = pipeline
        return FakeAggregate(self.documents)

    def find(self, query):
        ids = set(query["_id"]["$in"])
        return FakeFind([doc for doc in self.documents if doc["_id"] in ids])

    async def count_documents(self, _query):
        return len(self.documents)


def load_vector_helpers(namespace):
    source_path = Path(__file__).with_name("main.py")
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    wanted = {
        "build_vector_search_pipeline",
        "search_candidate_vectors",
        "search_job_vectors",
        "hydrate_vector_results",
        "match_candidates_for_job",
        "weaviate_overfetch_limit",
    }
    nodes = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in wanted
    ]
    module = ast.Module(body=nodes, type_ignores=[])
    ast.fix_missing_locations(module)
    exec(compile(module, str(source_path), "exec"), namespace)
    return namespace


class VectorBackendRoutingTests(unittest.TestCase):
    def test_mongodb_default_path_preserves_atlas_results(self):
        candidate = {"_id": ObjectId(), "name": "Existing", "score": 0.73}
        candidates = FakeCollection([candidate])
        helpers = load_vector_helpers(
            {
                "asyncio": asyncio,
                "ObjectId": ObjectId,
                "VECTOR_BACKEND": "mongodb",
                "candidates_collection": candidates,
                "jobs_collection": FakeCollection([]),
            }
        )

        result = asyncio.run(helpers["search_candidate_vectors"]([0.1], 1))

        self.assertEqual(result, [candidate])
        self.assertEqual(
            candidates.pipeline[0]["$vectorSearch"]["index"], "autoembed_index"
        )
        self.assertEqual(candidates.pipeline[1]["$addFields"]["score"],
                         {"$meta": "vectorSearchScore"})

    def test_weaviate_results_are_hydrated_in_rank_order(self):
        first_id, second_id = ObjectId(), ObjectId()
        candidates = FakeCollection(
            [
                {"_id": second_id, "name": "Second"},
                {"_id": first_id, "name": "First"},
            ]
        )
        vector_results = [
            {"candidate_id": str(first_id), "score": 0.95},
            {"candidate_id": str(second_id), "score": 0.8},
        ]
        helpers = load_vector_helpers(
            {
                "asyncio": asyncio,
                "ObjectId": ObjectId,
                "VECTOR_BACKEND": "weaviate",
                "candidates_collection": candidates,
                "jobs_collection": FakeCollection([]),
                "search_weaviate_candidates": lambda _vector, _limit: vector_results,
            }
        )

        result = asyncio.run(helpers["search_candidate_vectors"]([0.1], 2))

        self.assertEqual([item["name"] for item in result], ["First", "Second"])
        self.assertEqual([item["score"] for item in result], [0.95, 0.8])

    def test_weaviate_overfetch_discards_orphans_before_applying_limit(self):
        current_id = ObjectId()
        candidates = FakeCollection([{"_id": current_id, "name": "Current"}])
        vector_results = [
            {"candidate_id": str(ObjectId()), "score": 0.99},
            {"candidate_id": str(current_id), "score": 0.91},
        ]
        requested_limits = []

        def search(_vector, limit):
            requested_limits.append(limit)
            return vector_results

        helpers = load_vector_helpers(
            {
                "asyncio": asyncio,
                "ObjectId": ObjectId,
                "VECTOR_BACKEND": "weaviate",
                "candidates_collection": candidates,
                "jobs_collection": FakeCollection([]),
                "search_weaviate_candidates": search,
            }
        )

        result = asyncio.run(helpers["search_candidate_vectors"]([0.1], 1))

        self.assertEqual(requested_limits, [100])
        self.assertEqual([(item["name"], item["score"]) for item in result],
                         [("Current", 0.91)])

    def test_upload_response_contract_keys_remain_unchanged(self):
        source = Path(__file__).with_name("main.py").read_text(encoding="utf-8")
        for key in (
            '"job_ids": created_job_ids',
            '"matched_against_existing_candidates": matched_candidate_count',
            '"candidate_id": str(candidate_id)',
            '"matched_against_existing_jobs": len(top_jobs)',
        ):
            self.assertIn(key, source)

    def test_explicit_weaviate_matching_persists_hydrated_candidates(self):
        job_id = ObjectId()
        candidate_id = ObjectId()
        candidates = FakeCollection([{"_id": candidate_id, "name": "Candidate"}])
        persisted = []
        vector_results = [
            {"candidate_id": str(candidate_id), "score": 0.91},
        ]

        async def upsert(job, candidate, score):
            persisted.append((job, candidate, score))

        helpers = load_vector_helpers(
            {
                "asyncio": asyncio,
                "ObjectId": ObjectId,
                "VECTOR_BACKEND": "weaviate",
                "candidates_collection": candidates,
                "jobs_collection": FakeCollection([]),
                "search_weaviate_candidates": lambda _vector, _limit: vector_results,
                "upsert_match": upsert,
                "HTTPException": RuntimeError,
            }
        )

        count = asyncio.run(
            helpers["match_candidates_for_job"](job_id, {"embedding": [0.1]})
        )

        self.assertEqual(count, 1)
        self.assertEqual(persisted, [(job_id, candidate_id, 0.91)])


if __name__ == "__main__":
    unittest.main()
