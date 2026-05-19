import os
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from pymongo import MongoClient

MONGO_URL = os.getenv("MONGO_URL", "mongodb://mongodb:27017")
AUDIT_DB = os.getenv("AUDIT_DB", "rag_audit")
AUDIT_COLLECTION = os.getenv("AUDIT_COLLECTION", "logs")

_client = None
_db = None
_collection = None


def get_audit_collection():
    global _client, _db, _collection

    if _collection is None:
        # Connect with a timeout so the service can fail fast on startup.
        _client = MongoClient(MONGO_URL, serverSelectionTimeoutMS=5000)
        _db = _client[AUDIT_DB]
        _collection = _db[AUDIT_COLLECTION]

        # Indexes for common query patterns
        _collection.create_index("timestamp")
        _collection.create_index("service")
        _collection.create_index("action")
        _collection.create_index("correlation_id")

    return _collection


def generate_cid() -> str:
    return str(uuid.uuid4())


def log_action(
    service: str,
    action: str,
    payload: Optional[Dict[str, Any]] = None,
    correlation_id: Optional[str] = None,
    status: str = "success",
    error: Optional[str] = None,
):
    log_entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "service": service,
        "action": action,
        "payload": payload or {},
        "correlation_id": correlation_id or generate_cid(),
        "status": status,
        "error": error,
    }

    try:
        collection = get_audit_collection()
        collection.insert_one(log_entry)
    except Exception:
        # Logging must never crash the service.
        # (If Mongo is down, ingestion/retrieval should still work.)
        pass
