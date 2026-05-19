import os
import re
import math
import hashlib
import requests
from typing import List, Optional

# Embeddings used by ChromaDB. This module supports either:
# - Gemini embeddings (when GEMINI_API_KEY is set)
# - deterministic local embeddings fallback

EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "384"))
EMBEDDING_BACKEND = os.getenv("EMBEDDING_BACKEND", "").strip().lower()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()

_TOKEN_RE = re.compile(r"\b\w+\b", re.UNICODE)


def _local_embedding(text: str) -> List[float]:
    vector = [0.0] * EMBEDDING_DIM
    tokens = _TOKEN_RE.findall(text.lower())

    if not tokens:
        return vector

    for token in tokens:
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        index = int.from_bytes(digest[:4], "big") % EMBEDDING_DIM
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        weight = 1.0 + (len(token) / 10.0)
        vector[index] += sign * weight

    norm = math.sqrt(sum(value * value for value in vector))
    if norm:
        vector = [value / norm for value in vector]

    return vector


def _gemini_embeddings(texts: List[str], task_type: str) -> List[List[float]]:
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY not set")

    embeddings: List[List[float]] = []
    for text in texts:
        response = requests.post(
            "https://generativelanguage.googleapis.com/v1beta/models/"
            "gemini-embedding-001:embedContent",
            params={"key": GEMINI_API_KEY},
            json={
                "content": {"parts": [{"text": text}]},
                "taskType": task_type,
            },
            timeout=30,
        )
        response.raise_for_status()
        result = response.json()
        embeddings.append(result["embedding"]["values"])

    return embeddings


def embed_texts(texts: List[str], task_type: str) -> List[List[float]]:
    # Explicit backend override
    if EMBEDDING_BACKEND == "local":
        return [_local_embedding(text) for text in texts]

    # Prefer Gemini when key is present
    if GEMINI_API_KEY:
        try:
            return _gemini_embeddings(texts, task_type)
        except Exception:
            # Fallback to local embeddings so the service still works
            return [_local_embedding(text) for text in texts]

    # Default fallback
    return [_local_embedding(text) for text in texts]


def embed_query(text: str) -> List[float]:
    return embed_texts([text], task_type="RETRIEVAL_QUERY")[0]


def embed_documents(texts: List[str]) -> List[List[float]]:
    return embed_texts(texts, task_type="RETRIEVAL_DOCUMENT")


def get_collection_name(base_name: str = "documents") -> str:
    # If embeddings backend changes, it can be useful to isolate collections.
    backend_tag = "gemini" if GEMINI_API_KEY else "local"
    if EMBEDDING_BACKEND:
        backend_tag = EMBEDDING_BACKEND
    return f"{base_name}_{backend_tag}".strip()
