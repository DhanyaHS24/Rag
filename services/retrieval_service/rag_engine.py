import os
import asyncio
from typing import List, Optional

import chromadb
import google.generativeai as genai

from shared.embeddings import get_collection_name, embed_query
from shared.db_logger import log_action


CHROMA_URL = os.getenv("CHROMA_URL", "chromadb")
CHROMA_PORT = int(os.getenv("CHROMA_PORT", "8000"))

COLLECTION_NAME = get_collection_name("documents")

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


async def get_relevant_chunks(query: str, selected_docs: Optional[List[str]], username: str, cid: str) -> List[str]:
    q_emb = await asyncio.to_thread(embed_query, query)

    if selected_docs:
        if len(selected_docs) == 1:
            where = {
                "$and": [
                    {"source": selected_docs[0]},
                    {"username": username}
                ]
            }
        else:
            where = {
                "$and": [
                    {"source": {"$in": selected_docs}},
                    {"username": username}
                ]
            }
    else:
        where = {"username": username}

    res = await asyncio.to_thread(
        _collection.query,
        query_embeddings=[q_emb],
        n_results=5,
        where=where,
    )

    docs = res.get("documents", [[]])[0] if res else []
    return docs[:3]


def _generate_with_gemini(prompt: str, api_key: str) -> str:
    genai.configure(api_key=api_key)
    model_name = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
    model = genai.GenerativeModel(model_name)
    return model.generate_content(prompt).text


async def generate_response(query: str, contexts: List[str], api_key: str, cid: str) -> str:
    context = "\n\n".join(contexts)

    prompt = (
        "You are a helpful assistant. Use ONLY the following retrieved context to answer the user's question. "
        "If the answer is not contained in the context, say: 'I cannot answer this based on the provided documents.'\n\n"
        f"Context:\n{context}\n\n"
        f"User Question: {query}\n"
    )

    if not api_key:
        return "I cannot answer this based on the provided documents."

    try:
        answer = await asyncio.to_thread(_generate_with_gemini, prompt, api_key)
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
