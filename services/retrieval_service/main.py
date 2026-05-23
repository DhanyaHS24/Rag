import hashlib
import os
from datetime import datetime, timezone

import redis.asyncio as redis
from fastapi import BackgroundTasks, FastAPI, HTTPException, Depends
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field

from rag_engine import get_relevant_chunks, generate_response, is_greeting
from shared.auth import get_current_user
from shared.db_logger import generate_cid, log_action


GARNET_URL = os.getenv("GARNET_URL", "garnet:6379")
if not GARNET_URL.startswith("redis://"):
    GARNET_URL = f"redis://{GARNET_URL}"

MONGO_URL = os.getenv("MONGO_URL", "mongodb://mongodb:27017")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
CACHE_TTL_SECONDS = int(os.getenv("CACHE_TTL_SECONDS", "3600"))

app = FastAPI(title="Retrieval Service")
cache = redis.from_url(GARNET_URL, decode_responses=True)

mongo_client = AsyncIOMotorClient(MONGO_URL, serverSelectionTimeoutMS=5000)
db = mongo_client[os.getenv("AUDIT_DB", "rag_audit")]
logs_collection = db[os.getenv("CHAT_LOG_COLLECTION", "chat_logs")]


class ChatRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    selected_docs: list[str] = []


async def log_to_mongo(query: str, answer: str, cache_hit: bool, cid: str) -> None:
    await logs_collection.insert_one(
        {
            "timestamp": datetime.now(timezone.utc),
            "query": query,
            "answer": answer,
            "cache_hit": cache_hit,
            "correlation_id": cid,
        }
    )


def cache_key(request: ChatRequest) -> str:
    material = f"{request.query}|{'|'.join(sorted(request.selected_docs or []))}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


@app.post("/chat")
async def chat(
    request: ChatRequest,
    background_tasks: BackgroundTasks,
    username: str = Depends(get_current_user),
):
    cid = generate_cid()

    try:
        key = cache_key(request)
        cached = await cache.get(key)
        if cached:
            background_tasks.add_task(log_to_mongo, request.query, cached, True, cid)
            return {"answer": cached, "source": "cache", "correlation_id": cid}

        if is_greeting(request.query):
            answer = "Hello. Ask me a question about the selected documents, and I'll answer from the available context."
            await cache.setex(key, CACHE_TTL_SECONDS, answer)
            background_tasks.add_task(log_to_mongo, request.query, answer, False, cid)
            return {"answer": answer, "source": "system", "correlation_id": cid}

        contexts = await get_relevant_chunks(
            request.query,
            request.selected_docs or [],
            username=username,
            cid=cid,
        )

        if not contexts:
            answer = "No relevant documents found. Upload and process some documents first."
            await cache.setex(key, CACHE_TTL_SECONDS, answer)
            background_tasks.add_task(log_to_mongo, request.query, answer, False, cid)
            return {"answer": answer, "source": "system", "correlation_id": cid}

        answer = await generate_response(request.query, contexts, GEMINI_API_KEY, cid=cid)
        await cache.setex(key, CACHE_TTL_SECONDS, answer)
        background_tasks.add_task(log_to_mongo, request.query, answer, False, cid)

        return {
            "answer": answer,
            "source": "llm" if GEMINI_API_KEY else "fallback",
            "context_used": contexts,
            "correlation_id": cid,
        }

    except Exception as exc:
        log_action(
            service="retrieval_service",
            action="chat_error",
            payload={"error": str(exc)},
            correlation_id=cid,
            status="failed",
            error=str(exc),
        )
        raise HTTPException(status_code=500, detail="Internal Server Error during retrieval")


@app.get("/health")
async def health() -> dict[str, str]:
    await cache.ping()
    await mongo_client.admin.command("ping")
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8002)
