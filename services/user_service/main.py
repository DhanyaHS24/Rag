import os
from datetime import datetime, timezone
from typing import Any

import bcrypt
from fastapi import FastAPI, HTTPException, Header
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field

from shared.auth import create_token, verify_token


MONGO_URL = os.getenv("MONGO_URL", "mongodb://mongodb:27017")
DB_NAME = os.getenv("DB_NAME", "rag_users")

mongo_client = AsyncIOMotorClient(MONGO_URL, serverSelectionTimeoutMS=5000)
db = mongo_client[DB_NAME]
users = db["users"]

app = FastAPI(title="User Service")


class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=4, max_length=128)


class UserState(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    chat_sessions: list[dict[str, Any]] = []
    documents: list[dict[str, Any]] = []


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def public_user(document: dict[str, Any], token: str = "") -> dict[str, Any]:
    return {
        "username": document["username"],
        "chat_sessions": document.get("chat_sessions", []),
        "documents": document.get("documents", []),
        "token": token,
    }


@app.on_event("startup")
async def startup() -> None:
    await users.create_index("username", unique=True)


@app.get("/health")
async def health() -> dict[str, str]:
    await mongo_client.admin.command("ping")
    return {"status": "healthy"}


@app.post("/register")
async def register(credentials: Credentials) -> dict[str, Any]:
    existing = await users.find_one({"username": credentials.username})
    if existing:
        raise HTTPException(status_code=409, detail="Username already exists")

    document = {
        "username": credentials.username,
        "password_hash": bcrypt.hashpw(credentials.password.encode(), bcrypt.gensalt()).decode(),
        "chat_sessions": [],
        "documents": [],
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }
    await users.insert_one(document)
    token = create_token(credentials.username)
    return public_user(document, token=token)


@app.post("/login")
async def login(credentials: Credentials) -> dict[str, Any]:
    document = await users.find_one({"username": credentials.username})
    if not document or not bcrypt.checkpw(credentials.password.encode(), document["password_hash"].encode()):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    token = create_token(credentials.username)
    return public_user(document, token=token)


@app.post("/verify")
async def verify(authorization: str | None = Header(None, alias="Authorization")) -> dict[str, Any]:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header")
    token = authorization[7:]
    username = verify_token(token)
    if username is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    document = await users.find_one({"username": username})
    if not document:
        raise HTTPException(status_code=401, detail="User not found")
    return public_user(document)


@app.put("/state")
async def save_state(state: UserState, authorization: str | None = Header(None, alias="Authorization")) -> dict[str, str]:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header")
    token = authorization[7:]
    username = verify_token(token)
    if username is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    if state.username != username:
        raise HTTPException(status_code=403, detail="Cannot modify another user's state")
    result = await users.update_one(
        {"username": state.username},
        {
            "$set": {
                "chat_sessions": state.chat_sessions,
                "documents": state.documents,
                "updated_at": utc_now(),
            }
        },
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="User not found")
    return {"status": "saved"}


@app.get("/users/{username}")
async def get_user(username: str) -> dict[str, Any]:
    document = await users.find_one({"username": username})
    if not document:
        raise HTTPException(status_code=404, detail="User not found")
    return public_user(document)
