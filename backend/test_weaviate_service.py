import asyncio
import ast
import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from collections.abc import Callable
from unittest import mock

import weaviate_service as service


def load_migration_helpers(namespace=None):
    source_path = Path(__file__).with_name("migrate_vectors_to_weaviate.py")
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    nodes = [
        node
        for node in tree.body
        if (
            isinstance(node, ast.AsyncFunctionDef)
            and node.name in {"migrate_collection", "migrate"}
        )
        or (isinstance(node, ast.FunctionDef) and node.name == "main")
    ]
    module = ast.Module(body=nodes, type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {
        "asyncio": asyncio,
        "Any": Any,
        "Callable": Callable,
        **(namespace or {}),
    }
    exec(compile(module, str(source_path), "exec"), namespace)
    return namespace


class FakeQuery:
    def __init__(self, objects):
        self.objects = objects
        self.near_vector_calls = []

    def fetch_object_by_id(self, object_uuid):
        return self.objects.get(object_uuid)

    def near_vector(self, **kwargs):
        self.near_vector_calls.append(kwargs)
        return SimpleNamespace(objects=list(self.objects.values()))


class FakeData:
    def __init__(self, objects):
        self.objects = objects

    def insert(self, uuid, properties, vector):
        self.objects[uuid] = SimpleNamespace(
            properties=properties,
            vector=vector,
            metadata=SimpleNamespace(distance=0.2),
        )

    def update(self, uuid, properties, vector):
        self.insert(uuid, properties, vector)

    def delete_by_id(self, object_uuid):
        self.objects.pop(object_uuid, None)


class FakeCollection:
    def __init__(self):
        self.objects = {}
        self.query = FakeQuery(self.objects)
        self.data = FakeData(self.objects)


class FakeCollections:
    def __init__(self):
        self.collection = FakeCollection()

    def use(self, name):
        if name != service.VECTOR_COLLECTION:
            raise AssertionError(f"unexpected collection: {name}")
        return self.collection


class FakeSchemaCollections:
    def __init__(self, existing=None):
        self.created = []
        self.existing = set(existing or [])
        self.deleted = []

    def exists(self, name):
        return name in self.existing

    def create(self, **definition):
        self.created.append(definition)
        self.existing.add(definition["name"])

    def delete(self, name):
        self.existing.remove(name)
        self.deleted.append(name)


class FakeClient:
    def __init__(self):
        self.collections = FakeCollections()


class FakeCloudClient:
    def __init__(self, ready=True):
        self.ready = ready
        self.closed = False

    def is_ready(self):
        return self.ready

    def close(self):
        self.closed = True


class AsyncCursor:
    def __init__(self, documents):
        self.documents = iter(documents)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self.documents)
        except StopIteration as exc:
            raise StopAsyncIteration from exc


class FakeMongoCollection:
    def __init__(self, documents):
        self.documents = documents

    def find(self, *_args):
        return AsyncCursor(self.documents)


class WeaviateServiceTests(unittest.TestCase):
    def setUp(self):
        service.close_weaviate()
        self.client = FakeClient()

    def tearDown(self):
        service.close_weaviate()

    def test_connection_uses_environment_credentials_and_reuses_client(self):
        cloud_client = FakeCloudClient()
        with mock.patch.dict(
            os.environ,
            {"WEAVIATE_URL": "https://example.invalid", "WEAVIATE_API_KEY": "secret"},
            clear=False,
        ), mock.patch(
            "weaviate.connect_to_weaviate_cloud", return_value=cloud_client
        ) as connect:
            first = service.connect_to_weaviate()
            second = service.connect_to_weaviate()

        self.assertIs(first, cloud_client)
        self.assertIs(second, cloud_client)
        connect.assert_called_once()
        self.assertEqual(connect.call_args.kwargs["cluster_url"], "https://example.invalid")

    def test_failed_connection_readiness_closes_client(self):
        cloud_client = FakeCloudClient(ready=False)
        with mock.patch.dict(
            os.environ,
            {"WEAVIATE_URL": "https://example.invalid", "WEAVIATE_API_KEY": "secret"},
            clear=False,
        ), mock.patch(
            "weaviate.connect_to_weaviate_cloud", return_value=cloud_client
        ):
            with self.assertRaises(RuntimeError):
                service.connect_to_weaviate()
        self.assertTrue(cloud_client.closed)

    def test_collection_schema_uses_self_provided_vectors(self):
        collections = FakeSchemaCollections()
        service.ensure_collections(SimpleNamespace(collections=collections))

        self.assertEqual(
            [definition["name"] for definition in collections.created],
            [service.VECTOR_COLLECTION],
        )
        vector_properties = {
            prop.name for prop in collections.created[0]["properties"]
        }
        self.assertEqual(
            vector_properties,
            {
                "entity_type", "mongo_id", "candidate_id", "job_id", "name",
                "skills", "experience_years", "source_file", "title", "client",
            },
        )
        self.assertIsNotNone(collections.created[0]["vector_config"])

    def test_legacy_collections_are_removed_only_when_explicitly_requested(self):
        collections = FakeSchemaCollections(existing=service.LEGACY_COLLECTIONS)
        removed = service.remove_legacy_collections(
            SimpleNamespace(collections=collections)
        )
        self.assertEqual(removed, list(service.LEGACY_COLLECTIONS))
        self.assertEqual(collections.deleted, list(service.LEGACY_COLLECTIONS))

    def test_candidate_crud_is_idempotent(self):
        candidate = {
            "name": "Ada",
            "skills": ["Python"],
            "years_experience": 5,
            "source_file": "ada.pdf",
        }
        vector = [0.1, 0.2]
        self.assertTrue(
            service.insert_candidate_vector("mongo-1", candidate, vector, self.client)
        )
        self.assertFalse(
            service.insert_candidate_vector("mongo-1", candidate, vector, self.client)
        )
        results = service.search_candidates(vector, 10, self.client)
        self.assertEqual(results, [{"candidate_id": "mongo-1", "score": 0.9}])

        updated = {**candidate, "name": "Ada Lovelace"}
        service.update_candidate_vector("mongo-1", updated, vector, self.client)
        stored = next(iter(
            self.client.collections.use(service.VECTOR_COLLECTION).objects.values()
        ))
        self.assertEqual(stored.properties["name"], "Ada Lovelace")
        self.assertEqual(stored.properties["entity_type"], "candidate")
        self.assertEqual(stored.properties["mongo_id"], "mongo-1")
        search_call = self.client.collections.use(
            service.VECTOR_COLLECTION
        ).query.near_vector_calls[-1]
        self.assertIn("filters", search_call)
        self.assertEqual(search_call["filters"].target, "entity_type")
        self.assertEqual(search_call["filters"].value, "candidate")
        service.delete_candidate_vector("mongo-1", self.client)
        self.assertEqual(service.search_candidates(vector, 10, self.client), [])

    def test_job_crud_and_search(self):
        job = {"title": "Engineer", "client_name": "Acme"}
        self.assertTrue(service.insert_job_vector("job-1", job, [0.3], self.client))
        self.assertEqual(
            service.search_jobs([0.3], 1, self.client),
            [{"job_id": "job-1", "score": 0.9}],
        )
        stored = next(iter(
            self.client.collections.use(service.VECTOR_COLLECTION).objects.values()
        ))
        self.assertEqual(stored.properties["entity_type"], "job")
        self.assertEqual(stored.properties["mongo_id"], "job-1")
        search_call = self.client.collections.use(
            service.VECTOR_COLLECTION
        ).query.near_vector_calls[-1]
        self.assertEqual(search_call["filters"].target, "entity_type")
        self.assertEqual(search_call["filters"].value, "job")
        service.update_job_vector(
            "job-1", {**job, "title": "Senior Engineer"}, [0.4], self.client
        )
        service.delete_job_vector("job-1", self.client)
        self.assertEqual(service.search_jobs([0.4], 1, self.client), [])

    def test_score_normalization_matches_atlas_cosine_scale(self):
        self.assertEqual(service.atlas_score_from_weaviate_distance(0), 1.0)
        self.assertEqual(service.atlas_score_from_weaviate_distance(1), 0.5)
        self.assertEqual(service.atlas_score_from_weaviate_distance(2), 0.0)
        self.assertEqual(service.atlas_score_from_weaviate_distance(-1), 1.0)
        self.assertEqual(service.atlas_score_from_weaviate_distance(3), 0.0)

    def test_migration_skips_existing_and_missing_vectors(self):
        documents = [
            {"_id": "one", "embedding": [0.1], "name": "One"},
            {"_id": "two", "embedding": [0.2], "name": "Two"},
            {"_id": "three", "name": "Three"},
        ]
        calls = []

        def insert(object_id, _document, _vector):
            calls.append(object_id)
            return object_id == "one"

        counts = asyncio.run(
            load_migration_helpers()["migrate_collection"](
                FakeMongoCollection(documents), "test", insert, dry_run=False
            )
        )
        self.assertEqual(calls, ["one", "two"])
        self.assertEqual(
            counts,
            {"eligible": 2, "migrated": 1, "skipped": 1, "missing_vector": 1},
        )

    def test_migration_dry_run_never_inserts(self):
        collection = FakeMongoCollection([{"_id": "one", "embedding": [0.1]}])

        def unexpected_insert(*_args):
            self.fail("dry-run attempted to insert a vector")

        counts = asyncio.run(
            load_migration_helpers()["migrate_collection"](
                collection, "test", unexpected_insert, dry_run=True
            )
        )
        self.assertEqual(counts["eligible"], 1)
        self.assertEqual(counts["migrated"], 0)

    def test_migration_closes_connection_when_collection_creation_fails(self):
        events = []
        cloud_client = SimpleNamespace(collections=FakeSchemaCollections())

        def connect():
            events.append("connect")
            return cloud_client

        def ensure(*_args):
            events.append("ensure")
            raise RuntimeError("collection creation failed")

        def close():
            events.append("close")

        helpers = load_migration_helpers(
            {
                "connect_to_weaviate": connect,
                "ensure_collections": ensure,
                "close_weaviate": close,
                "LEGACY_COLLECTIONS": service.LEGACY_COLLECTIONS,
                "VECTOR_COLLECTION": service.VECTOR_COLLECTION,
                "remove_legacy_collections": service.remove_legacy_collections,
                "candidates_collection": FakeMongoCollection([]),
                "jobs_collection": FakeMongoCollection([]),
                "insert_candidate_vector": lambda *_args: True,
                "insert_job_vector": lambda *_args: True,
            }
        )
        with self.assertRaises(RuntimeError):
            asyncio.run(helpers["migrate"]())
        self.assertEqual(events, ["connect", "ensure", "close"])

    def test_standalone_main_closes_mongo_and_weaviate_on_success(self):
        events = []
        mongo = SimpleNamespace(close=lambda: events.append("mongo-close"))

        async def migrate_success(**_kwargs):
            return {"candidates": self._empty_counts(), "jobs": self._empty_counts()}

        helpers = load_migration_helpers(
            {
                "argparse": __import__("argparse"),
                "close_weaviate": lambda: events.append("weaviate-close"),
                "mongo_client": mongo,
            }
        )
        helpers["migrate"] = migrate_success
        with mock.patch("sys.argv", ["migration", "--dry-run"]):
            helpers["main"]()
        self.assertEqual(events, ["weaviate-close", "mongo-close"])

    def test_standalone_main_closes_mongo_and_weaviate_on_failure(self):
        events = []
        mongo = SimpleNamespace(close=lambda: events.append("mongo-close"))

        async def migrate_failure(**_kwargs):
            raise RuntimeError("MongoDB failed")

        helpers = load_migration_helpers(
            {
                "argparse": __import__("argparse"),
                "close_weaviate": lambda: events.append("weaviate-close"),
                "mongo_client": mongo,
            }
        )
        helpers["migrate"] = migrate_failure
        with mock.patch("sys.argv", ["migration"]), self.assertRaises(RuntimeError):
            helpers["main"]()
        self.assertEqual(events, ["weaviate-close", "mongo-close"])

    @staticmethod
    def _empty_counts():
        return {"eligible": 0, "migrated": 0, "skipped": 0, "missing_vector": 0}


if __name__ == "__main__":
    unittest.main()
