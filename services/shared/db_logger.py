import os
import uuid
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from pymongo import MongoClient

logger = logging.getLogger(__name__)

MONGO_URL = os.getenv("MONGO_URL", "mongodb://mongodb:27017")
AUDIT_DB = os.getenv("AUDIT_DB", "rag_audit")
AUDIT_COLLECTION = os.getenv("AUDIT_COLLECTION", "logs")

_client = None
_collection = None


def get_audit_collection():
    global _client, _collection

    if _collection is None:
        _client = MongoClient(MONGO_URL, serverSelectionTimeoutMS=5000)
        db = _client[AUDIT_DB]
        _collection = db[AUDIT_COLLECTION]
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
) -> None:
    log_entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "service": service,
        "action": action,
        "payload": payload or {},
        "correlation_id": correlation_id or generate_cid(),
        "status": status,
        "error": error,
    }

    logger.info("AUDIT: %s/%s [%s] %s", service, action, status, correlation_id or "")

    try:
        get_audit_collection().insert_one(log_entry)
    except Exception as exc:
        logger.error("Failed to write audit log to MongoDB: %s", exc)

logger.setLevel(logging.INFO)
logger.addHandler(logging.StreamHandler())
