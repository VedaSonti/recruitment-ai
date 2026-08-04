import importlib
import os
import re
import sys
import types
import unittest
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

from bson import ObjectId
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from pymongo.errors import DuplicateKeyError


class Result:
    def __init__(self, inserted_id=None, matched_count=0):
        self.inserted_id = inserted_id
        self.matched_count = matched_count


def matches(document, query):
    for key, expected in query.items():
        actual = document.get(key)
        if isinstance(expected, dict) and "$gt" in expected:
            if actual is None or actual <= expected["$gt"]:
                return False
        elif actual != expected:
            return False
    return True


class FakeCollection:
    def __init__(self, unique_field=None):
        self.documents = []
        self.unique_field = unique_field

    async def insert_one(self, document):
        stored = deepcopy(document)
        stored.setdefault("_id", ObjectId())
        if self.unique_field and any(
            item.get(self.unique_field) == stored.get(self.unique_field)
            for item in self.documents
        ):
            raise DuplicateKeyError("duplicate")
        self.documents.append(stored)
        return Result(inserted_id=stored["_id"])

    async def find_one(self, query):
        return next((item for item in self.documents if matches(item, query)), None)

    async def update_one(self, query, update):
        document = await self.find_one(query)
        if not document:
            return Result(matched_count=0)
        document.update(update.get("$set", {}))
        for key, amount in update.get("$inc", {}).items():
            document[key] = document.get(key, 0) + amount
        return Result(matched_count=1)

    async def delete_many(self, query):
        self.documents = [item for item in self.documents if not matches(item, query)]

    async def find_one_and_update(self, query, update, return_document=None):
        document = await self.find_one(query)
        if not document:
            return None
        document.update(update.get("$set", {}))
        return document


recruiters = FakeCollection(unique_field="email_normalized")
reset_tokens = FakeCollection(unique_field="token_hash")
fake_db = types.ModuleType("db")
fake_db.recruiter_users_collection = recruiters
fake_db.password_reset_tokens_collection = reset_tokens
sys.modules["db"] = fake_db
os.environ.setdefault("AUTH_SECRET", "test-only-auth-secret-that-is-long-and-random-enough")
os.environ.setdefault("APP_ENV", "development")
auth = importlib.import_module("auth")


def build_app():
    app = FastAPI()
    app.include_router(auth.router)

    @app.get("/protected")
    async def protected(_user=Depends(auth.get_current_recruiter)):
        return {"protected": True}

    @app.get("/interviews/public-token")
    async def public_interview():
        return {"public": True}

    return app


class AuthenticationTests(unittest.TestCase):
    def setUp(self):
        recruiters.documents.clear()
        reset_tokens.documents.clear()
        auth._login_attempts.clear()
        auth.APP_ENV = "development"
        self.sent_email = {}

        def capture_email(to_address, subject, html):
            self.sent_email.update(to=to_address, subject=subject, html=html)
            return True

        auth.send_email = capture_email
        self.client = TestClient(build_app())

    def create_user(self, email="recruiter@isoftanz.com.au", password="SecurePassword1"):
        import asyncio
        return asyncio.run(auth.create_recruiter_account(email, "Recruiter Name", password))

    def test_recruiter_creation_hashes_password_and_rejects_duplicate_email(self):
        self.create_user(email="Recruiter@iSoftANZ.com.au")
        stored = recruiters.documents[0]
        self.assertEqual(stored["email_normalized"], "recruiter@isoftanz.com.au")
        self.assertNotIn("password", stored)
        self.assertNotEqual(stored["password_hash"], "SecurePassword1")
        self.assertTrue(auth.verify_password(stored["password_hash"], "SecurePassword1"))
        with self.assertRaises(ValueError):
            self.create_user(email="recruiter@isoftanz.com.au")

    def test_login_sets_session_and_me_returns_only_safe_user(self):
        self.create_user()
        response = self.client.post("/auth/login", json={"email": "RECRUITER@isoftanz.com.au", "password": "SecurePassword1"})
        self.assertEqual(response.status_code, 200)
        cookie = response.headers["set-cookie"].lower()
        self.assertIn("httponly", cookie)
        self.assertIn("samesite=lax", cookie)
        self.assertNotIn("secure", cookie)
        me = self.client.get("/auth/me")
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json()["user"]["email"], "recruiter@isoftanz.com.au")
        self.assertNotIn("password_hash", me.text)
        self.assertEqual(self.client.get("/protected").status_code, 200)

    def test_login_failures_are_generic_and_inactive_user_is_rejected(self):
        self.create_user()
        unknown = self.client.post("/auth/login", json={"email": "unknown@example.com", "password": "WrongPassword1"})
        wrong = self.client.post("/auth/login", json={"email": "recruiter@isoftanz.com.au", "password": "WrongPassword1"})
        self.assertEqual(unknown.status_code, 401)
        self.assertEqual(unknown.json(), wrong.json())
        recruiters.documents[0]["is_active"] = False
        inactive = self.client.post("/auth/login", json={"email": "recruiter@isoftanz.com.au", "password": "SecurePassword1"})
        self.assertEqual(inactive.status_code, 401)
        self.assertNotIn("password_hash", inactive.text)

    def test_logout_clears_cookie_and_invalidates_protected_access(self):
        self.create_user()
        self.client.post("/auth/login", json={"email": "recruiter@isoftanz.com.au", "password": "SecurePassword1"})
        response = self.client.post("/auth/logout")
        self.assertEqual(response.status_code, 200)
        self.assertIn("max-age=0", response.headers["set-cookie"].lower())
        self.assertEqual(self.client.get("/protected").status_code, 401)

    def test_internal_route_requires_auth_but_candidate_route_is_public(self):
        self.assertEqual(self.client.get("/protected").status_code, 401)
        self.assertEqual(self.client.get("/interviews/public-token").status_code, 200)
        source = Path(__file__).with_name("main.py").read_text(encoding="utf-8")
        self.assertIn('@app.get("/interviews/{token}")', source)
        self.assertIn('@app.post("/interviews/{token}/respond-video")', source)
        self.assertNotIn('@app.get("/interviews/{token}", dependencies=', source)

    def test_forgot_password_is_generic_and_stores_only_token_hash(self):
        self.create_user()
        existing = self.client.post("/auth/forgot-password", json={"email": "recruiter@isoftanz.com.au"})
        unknown = self.client.post("/auth/forgot-password", json={"email": "unknown@example.com"})
        self.assertEqual(existing.json(), unknown.json())
        self.assertEqual(len(reset_tokens.documents), 1)
        stored = reset_tokens.documents[0]
        self.assertRegex(stored["token_hash"], r"^[a-f0-9]{64}$")
        self.assertNotIn(stored["token_hash"], self.sent_email["html"])
        self.assertGreater(stored["expires_at"], datetime.now(timezone.utc))

    def test_reset_token_is_single_use_and_changes_password(self):
        self.create_user()
        self.client.post("/auth/forgot-password", json={"email": "recruiter@isoftanz.com.au"})
        raw_token = re.search(r"token=([A-Za-z0-9_-]+)", self.sent_email["html"]).group(1)
        reset = self.client.post("/auth/reset-password", json={"token": raw_token, "new_password": "NewSecurePassword2"})
        self.assertEqual(reset.status_code, 200)
        self.assertFalse(auth.verify_password(recruiters.documents[0]["password_hash"], "SecurePassword1"))
        self.assertTrue(auth.verify_password(recruiters.documents[0]["password_hash"], "NewSecurePassword2"))
        reused = self.client.post("/auth/reset-password", json={"token": raw_token, "new_password": "AnotherPassword3"})
        self.assertEqual(reused.status_code, 400)
        invalid = self.client.post("/auth/reset-password", json={"token": "x" * 40, "new_password": "AnotherPassword3"})
        self.assertEqual(invalid.status_code, 400)

    def test_expired_reset_token_is_rejected(self):
        self.create_user()
        reset_tokens.documents.append({
            "_id": ObjectId(),
            "user_id": recruiters.documents[0]["_id"],
            "token_hash": auth.hashlib.sha256(b"expired-token-value-with-enough-length").hexdigest(),
            "expires_at": datetime.now(timezone.utc) - timedelta(minutes=1),
            "used_at": None,
        })
        response = self.client.post("/auth/reset-password", json={"token": "expired-token-value-with-enough-length", "new_password": "AnotherPassword3"})
        self.assertEqual(response.status_code, 400)

    def test_production_cookie_is_secure(self):
        self.create_user()
        auth.APP_ENV = "production"
        response = self.client.post("/auth/login", json={"email": "recruiter@isoftanz.com.au", "password": "SecurePassword1"})
        self.assertIn("secure", response.headers["set-cookie"].lower())

    def test_cors_is_credentialed_and_has_no_wildcard_origin(self):
        source = Path(__file__).with_name("main.py").read_text(encoding="utf-8")
        self.assertIn("allow_credentials=True", source)
        origins = source.split("allow_origins=[", 1)[1].split("]", 1)[0]
        self.assertNotIn('"*"', origins)
        self.assertIn('"http://localhost:3000"', origins)


if __name__ == "__main__":
    unittest.main()
