import os
import hashlib
from typing import List, Optional, Dict, Any

import chromadb
import google.generativeai as genai

from shared.embeddings import get_collection_name, embed_query
from shared.db_logger import log_action


CHROMA_URL = os.getenv("CHROMA_URL", "chromadb")
CHROMA_PORT = int(os.getenv("CHROMA_PORT", "8000"))

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()

COLLECTION_NAME = get_collection_name("documents")

# Chroma client and collection (embedding function is handled by passing query embeddings)
_client = chromadb.HttpClient(host=CHROMA_URL, port=CHROMA_PORT)
_collection = _client.get_or_create_collection(name=COLLECTION_NAME)


class ChatRequest:
    def __init__(self, query: str, selected_docs: Optional[List[str]] = None):
        self.query = query
        self.selected_docs = selected_docs or []


def is_greeting(text: str) -> bool:
    t = (text or "").strip().lower()
    greetings = {"hi", "hello", "hey", "good morning",
                 "good afternoon", "good evening"}
    if t in greetings:
        return True
    return any(t.startswith(g) for g in greetings)


def get_relevant_chunks(query: str, selected_docs: Optional[List[str]], cid: str) -> List[str]:
    # Chroma "where" filtering is driver/version-dependent. To keep it robust,
    # we do filtering at app level after querying by embedding.
    q_emb = embed_query(query)

    where = None
    if selected_docs:
        # Chroma expects a Mongo-like filter; $in support may vary.
        # We'll attempt it, but if it fails, we fall back to unfiltered results.
        if len(selected_docs) == 1:
            where = {"source": selected_docs[0]}
        else:
            where = {"source": {"$in": selected_docs}}

    try:
        res = _collection.query(
            query_embeddings=[q_emb],
            n_results=5,
            where=where,
        )
    except Exception:
        res = _collection.query(query_embeddings=[q_emb], n_results=5)

    docs = res.get("documents", [[]])[0] if res else []
    return docs[:3]


def _generate_with_gemini(prompt: str, api_key: str) -> str:
    genai.configure(api_key=api_key)
    model_name = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
    model = genai.GenerativeModel(model_name)
    return model.generate_content(prompt).text


def generate_response(query: str, contexts: List[str], api_key: str, cid: str) -> str:
    context = "\n\n".join(contexts)

    prompt = (
        "You are a helpful assistant. Use ONLY the following retrieved context to answer the user's question. "
        "If the answer is not contained in the context, say: 'I cannot answer this based on the provided documents.'\n\n"
        f"Context:\n{context}\n\n"
        f"User Question: {query}\n"
    )

    # If no Gemini key is set, return a deterministic fallback.
    if not api_key:
        return "I cannot answer this based on the provided documents."

    try:
        answer = _generate_with_gemini(prompt, api_key)
        return answer.strip()
    except Exception as e:
        log_action(
            service="retrieval_service",
            action="gemini_error",
            payload={"error": str(e)},
            correlation_id=cid,
            status="failed",
            error=str(e),
        )
        return "I cannot answer this based on the provided documents."
