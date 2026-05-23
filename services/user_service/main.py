import os
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, HTTPException
from motor.motor_asyncio import AsyncIOMotorClient
from passlib.context import CryptContext
from pydantic import BaseModel, Field


MONGO_URL = os.getenv("MONGO_URL", "mongodb://mongodb:27017")
DB_NAME = os.getenv("DB_NAME", "rag_users")

mongo_client = AsyncIOMotorClient(MONGO_URL, serverSelectionTimeoutMS=5000)
db = mongo_client[DB_NAME]
users = db["users"]
password_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

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


def public_user(document: dict[str, Any]) -> dict[str, Any]:
    return {
        "username": document["username"],
        "chat_sessions": document.get("chat_sessions", []),
        "documents": document.get("documents", []),
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
        "password_hash": password_context.hash(credentials.password),
        "chat_sessions": [],
        "documents": [],
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }
    await users.insert_one(document)
    return public_user(document)


@app.post("/login")
async def login(credentials: Credentials) -> dict[str, Any]:
    document = await users.find_one({"username": credentials.username})
    if not document or not password_context.verify(credentials.password, document["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    return public_user(document)


@app.put("/state")
async def save_state(state: UserState) -> dict[str, str]:
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
