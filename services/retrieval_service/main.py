import os
import hashlib

import redis.asyncio as redis
from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel
from motor.motor_asyncio import AsyncIOMotorClient

from shared.db_logger import log_action, generate_cid

from .rag_engine import get_relevant_chunks, generate_response, is_greeting


GARNET_URL = os.getenv("GARNET_URL", "garnet:6379")
# Most Redis-compatible caches expose as redis://host:port
GARNET_URL = os.getenv("GARNET_URL", "garnet:6379")
if not GARNET_URL.startswith("redis://"):
    GARNET_URL = f"redis://{GARNET_URL}"

MONGO_URL = os.getenv("MONGO_URL", "mongodb://mongodb:27017")


GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()


app = FastAPI(title="Retrieval Service")

cache = redis.from_url(GARNET_URL)

mongo_client = AsyncIOMotorClient(MONGO_URL)
db = mongo_client[os.getenv("AUDIT_DB", "rag_audit")]
logs_collection = db[os.getenv("AUDIT_COLLECTION", "chat_logs")]


class ChatRequest(BaseModel):
    query: str
    selected_docs: list[str] = []


async def log_to_mongo(query: str, answer: str, cache_hit: bool, cid: str):
    # Use UTC timestamps; don't block request.
    doc = {
        "timestamp": __import__("datetime").datetime.utcnow(),
        "query": query,
        "answer": answer,
        "cache_hit": cache_hit,
        "correlation_id": cid,
    }
    await logs_collection.insert_one(doc)


@app.post("/chat")
async def chat(request: ChatRequest, background_tasks: BackgroundTasks):
    cid = generate_cid()

    try:
        query_hash = hashlib.md5(request.query.encode("utf-8")).hexdigest()

        cached = await cache.get(query_hash)
        if cached:
            answer = cached.decode("utf-8")
            background_tasks.add_task(
                log_to_mongo, request.query, answer, True, cid)
            return {"answer": answer, "source": "cache"}

        # Greeting shortcut
        if is_greeting(request.query):
            answer = (
                "Hello. Ask me a question about the selected documents, and I’ll answer from the available context."
            )
            await cache.setex(query_hash, 3600, answer)
            background_tasks.add_task(
                log_to_mongo, request.query, answer, False, cid)
            return {"answer": answer, "source": "system"}

        contexts = get_relevant_chunks(
            request.query,
            request.selected_docs or [],
            cid=cid,
        )

        if not contexts:
            answer = "No relevant documents found. Upload and process some documents first."
            await cache.setex(query_hash, 3600, answer)
            background_tasks.add_task(
                log_to_mongo, request.query, answer, False, cid)
            return {"answer": answer, "source": "system"}

        answer = generate_response(
            request.query, contexts, GEMINI_API_KEY, cid=cid)

        await cache.setex(query_hash, 3600, answer)
        background_tasks.add_task(
            log_to_mongo, request.query, answer, False, cid)

        return {"answer": answer, "source": "llm", "context_used": contexts}

    except Exception as e:
        log_action(
            service="retrieval_service",
            action="chat_error",
            payload={"error": str(e)},
            correlation_id=cid,
            status="failed",
            error=str(e),
        )
        raise HTTPException(
            status_code=500, detail="Internal Server Error during retrieval")


@app.get("/health")
async def health():
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8002)
