"""Recruiter authentication, secure sessions, and password-reset workflow."""

import hashlib
import os
import re
import secrets
import time
from html import escape
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from bson import ObjectId
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, EmailStr, Field
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from db import password_reset_tokens_collection, recruiter_users_collection
from email_service import send_email


APP_ENV = os.getenv("APP_ENV", "development").lower()
AUTH_COOKIE_NAME = os.getenv("AUTH_COOKIE_NAME", "recruitment_session")
AUTH_SESSION_HOURS = max(1, int(os.getenv("AUTH_SESSION_HOURS", "8")))
AUTH_REMEMBER_DAYS = max(1, int(os.getenv("AUTH_REMEMBER_DAYS", "30")))
AUTH_SECRET = os.getenv("AUTH_SECRET", "")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000").rstrip("/")
RESET_TOKEN_MINUTES = max(5, int(os.getenv("AUTH_RESET_TOKEN_MINUTES", "30")))

if not AUTH_SECRET:
    if APP_ENV == "production":
        raise RuntimeError("AUTH_SECRET must be configured in production")
    AUTH_SECRET = secrets.token_urlsafe(48)
    print("[auth] Using an ephemeral development secret; sessions reset on backend restart")

JWT_ALGORITHM = "HS256"
password_hasher = PasswordHasher()
_dummy_password_hash = password_hasher.hash(secrets.token_urlsafe(24))
router = APIRouter(prefix="/auth", tags=["authentication"])


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)
    remember_me: bool = False


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=32, max_length=512)
    new_password: str = Field(min_length=12, max_length=256)


def normalize_email(email: str) -> str:
    return email.strip().lower()


def validate_password_policy(password: str) -> None:
    if (
        len(password) < 12
        or not re.search(r"[a-z]", password)
        or not re.search(r"[A-Z]", password)
        or not re.search(r"\d", password)
    ):
        raise ValueError(
            "Password must be at least 12 characters and include uppercase, lowercase, and a number."
        )


def hash_password(password: str) -> str:
    validate_password_policy(password)
    return password_hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return bool(password_hasher.verify(password_hash, password))
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def build_recruiter_document(email: str, full_name: str, password: str) -> dict:
    normalized = normalize_email(email)
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", normalized):
        raise ValueError("Enter a valid email address.")
    if not full_name.strip():
        raise ValueError("Recruiter name is required.")
    now = datetime.now(timezone.utc)
    return {
        "email": normalized,
        "email_normalized": normalized,
        "full_name": full_name.strip(),
        "role": "recruiter",
        "password_hash": hash_password(password),
        "is_active": True,
        "session_version": 1,
        "created_at": now,
        "updated_at": now,
        "last_login_at": None,
    }


async def create_recruiter_account(email: str, full_name: str, password: str) -> dict:
    document = build_recruiter_document(email, full_name, password)
    try:
        result = await recruiter_users_collection.insert_one(document)
    except DuplicateKeyError as exc:
        raise ValueError("A recruiter with that email already exists.") from exc
    document["_id"] = result.inserted_id
    return safe_recruiter(document)


def safe_recruiter(user: dict) -> dict:
    return {
        "user_id": str(user["_id"]),
        "email": user["email"],
        "full_name": user.get("full_name") or "Recruiter",
        "role": user.get("role", "recruiter"),
    }


def create_session_token(user: dict, remember_me: bool = False) -> tuple[str, int]:
    now = datetime.now(timezone.utc)
    lifetime = (
        timedelta(days=AUTH_REMEMBER_DAYS)
        if remember_me
        else timedelta(hours=AUTH_SESSION_HOURS)
    )
    expires_at = now + lifetime
    token = jwt.encode(
        {
            "sub": str(user["_id"]),
            "role": user.get("role", "recruiter"),
            "ver": int(user.get("session_version", 1)),
            "iat": now,
            "exp": expires_at,
        },
        AUTH_SECRET,
        algorithm=JWT_ALGORITHM,
    )
    return token, int(lifetime.total_seconds())


def decode_session_token(token: str) -> dict:
    return jwt.decode(token, AUTH_SECRET, algorithms=[JWT_ALGORITHM])


def set_session_cookie(response: Response, token: str, max_age: int) -> None:
    response.set_cookie(
        key=AUTH_COOKIE_NAME,
        value=token,
        max_age=max_age,
        httponly=True,
        secure=APP_ENV == "production",
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        key=AUTH_COOKIE_NAME,
        httponly=True,
        secure=APP_ENV == "production",
        samesite="lax",
        path="/",
    )


async def get_current_recruiter(request: Request) -> dict:
    token = request.cookies.get(AUTH_COOKIE_NAME)
    if not token:
        raise HTTPException(401, "Authentication required")
    try:
        claims = decode_session_token(token)
        user_id = claims.get("sub", "")
        if not ObjectId.is_valid(user_id):
            raise ValueError("invalid subject")
    except (jwt.InvalidTokenError, ValueError, TypeError):
        raise HTTPException(401, "Invalid or expired session")

    if claims.get("role") != "recruiter":
        raise HTTPException(403, "Recruiter access required")
    user = await recruiter_users_collection.find_one({"_id": ObjectId(user_id)})
    if not user or not user.get("is_active"):
        raise HTTPException(401, "Invalid or expired session")
    if int(claims.get("ver", 0)) != int(user.get("session_version", 1)):
        raise HTTPException(401, "Invalid or expired session")
    if user.get("role") != "recruiter":
        raise HTTPException(403, "Recruiter access required")
    return user


_login_attempts: dict[str, deque[float]] = defaultdict(deque)


def enforce_login_rate_limit(request: Request, email: str) -> None:
    key = f"{request.client.host if request.client else 'unknown'}:{normalize_email(email)}"
    now = time.monotonic()
    attempts = _login_attempts[key]
    while attempts and attempts[0] < now - 900:
        attempts.popleft()
    if len(attempts) >= 8:
        raise HTTPException(429, "Too many sign-in attempts. Please try again later.")
    attempts.append(now)


@router.post("/login")
async def login(body: LoginRequest, request: Request, response: Response):
    normalized = normalize_email(str(body.email))
    enforce_login_rate_limit(request, normalized)
    user = await recruiter_users_collection.find_one({"email_normalized": normalized})
    stored_hash = user.get("password_hash", "") if user else _dummy_password_hash
    password_valid = verify_password(stored_hash, body.password)
    if not user or not password_valid or not user.get("is_active"):
        raise HTTPException(401, "Invalid email or password")

    now = datetime.now(timezone.utc)
    if password_hasher.check_needs_rehash(stored_hash):
        await recruiter_users_collection.update_one(
            {"_id": user["_id"]},
            {"$set": {"password_hash": password_hasher.hash(body.password), "updated_at": now}},
        )
    await recruiter_users_collection.update_one(
        {"_id": user["_id"]},
        {"$set": {"last_login_at": now}},
    )
    token, max_age = create_session_token(user, body.remember_me)
    set_session_cookie(response, token, max_age)
    return {"user": safe_recruiter(user)}


@router.post("/logout")
async def logout(request: Request, response: Response):
    token = request.cookies.get(AUTH_COOKIE_NAME)
    if token:
        try:
            claims = decode_session_token(token)
            user_id = claims.get("sub", "")
            if ObjectId.is_valid(user_id):
                await recruiter_users_collection.update_one(
                    {"_id": ObjectId(user_id)},
                    {"$inc": {"session_version": 1}, "$set": {"updated_at": datetime.now(timezone.utc)}},
                )
        except (jwt.InvalidTokenError, TypeError):
            pass
    clear_session_cookie(response)
    return {"message": "Signed out"}


@router.get("/me")
async def me(request: Request):
    user = await get_current_recruiter(request)
    return {"user": safe_recruiter(user)}


def _reset_email_html(full_name: str, reset_url: str) -> str:
    return f"""
    <div style="font-family:Arial,sans-serif;background:#f7f3f4;padding:32px;color:#333333">
      <div style="max-width:600px;margin:auto;background:white;border-radius:12px;overflow:hidden;border:1px solid #ead7db">
        <div style="background:#5C0D1B;padding:24px 30px;color:white"><strong style="font-size:22px;color:#E01111">iSOFT</strong> Recruitment</div>
        <div style="padding:30px">
          <h1 style="font-size:24px;margin:0 0 16px">Reset your password</h1>
          <p>Hello {escape(full_name)},</p>
          <p>A password reset was requested for your recruiter account. This link expires in {RESET_TOKEN_MINUTES} minutes.</p>
          <p style="margin:28px 0"><a href="{reset_url}" style="background:#5C0D1B;color:white;text-decoration:none;padding:13px 20px;border-radius:8px;font-weight:bold">Reset password</a></p>
          <p style="font-size:13px;color:#777">If you did not request this, you can ignore this email.</p>
        </div>
      </div>
    </div>
    """


@router.post("/forgot-password")
async def forgot_password(body: ForgotPasswordRequest):
    generic = {"message": "If an active account exists, a password reset email has been sent."}
    try:
        user = await recruiter_users_collection.find_one(
            {"email_normalized": normalize_email(str(body.email)), "is_active": True}
        )
        if not user:
            return generic
        await password_reset_tokens_collection.delete_many(
            {"user_id": user["_id"], "used_at": None}
        )
        raw_token = secrets.token_urlsafe(48)
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        now = datetime.now(timezone.utc)
        await password_reset_tokens_collection.insert_one(
            {
                "user_id": user["_id"],
                "token_hash": token_hash,
                "created_at": now,
                "expires_at": now + timedelta(minutes=RESET_TOKEN_MINUTES),
                "used_at": None,
            }
        )
        reset_url = f"{FRONTEND_URL}/reset-password?token={raw_token}"
        await run_in_threadpool(
            send_email,
            user["email"],
            "Reset your iSOFT Recruitment password",
            _reset_email_html(user.get("full_name") or "Recruiter", reset_url),
        )
    except Exception as exc:
        print(f"[auth] Password-reset request failed safely ({type(exc).__name__})")
    return generic


@router.post("/reset-password")
async def reset_password(body: ResetPasswordRequest):
    try:
        validate_password_policy(body.new_password)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    token_hash = hashlib.sha256(body.token.encode("utf-8")).hexdigest()
    now = datetime.now(timezone.utc)
    token_doc = await password_reset_tokens_collection.find_one_and_update(
        {
            "token_hash": token_hash,
            "used_at": None,
            "expires_at": {"$gt": now},
        },
        {"$set": {"used_at": now}},
        return_document=ReturnDocument.AFTER,
    )
    if not token_doc:
        raise HTTPException(400, "This password reset link is invalid or has expired.")
    await recruiter_users_collection.update_one(
        {"_id": token_doc["user_id"], "is_active": True},
        {
            "$set": {"password_hash": password_hasher.hash(body.new_password), "updated_at": now},
            "$inc": {"session_version": 1},
        },
    )
    await password_reset_tokens_collection.delete_many(
        {"user_id": token_doc["user_id"], "used_at": None}
    )
    return {"message": "Password reset successfully. You can now sign in."}
