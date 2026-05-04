from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import List, Optional
import redis.asyncio as redis
from motor.motor_asyncio import AsyncIOMotorClient
import chromadb
from chromadb.utils import embedding_functions
import google.generativeai as genai
import json
import hashlib
from datetime import datetime

# --- Configuration ---
GARNET_URL = "redis://localhost:3278"  # Garnet uses the Redis protocol
MONGO_URL = "mongodb://localhost:27017"
CHROMA_URL = "localhost"
CHROMA_PORT = 8001
GEMINI_API_KEY = "YOUR_GEMINI_API_KEY_HERE"  # Replace with your actual key

# --- Initialize Clients ---
app = FastAPI(title="Retrieval Service")
cache = redis.from_url(GARNET_URL)
mongo_client = AsyncIOMotorClient(MONGO_URL)
db = mongo_client.rag_audit
logs_collection = db.chat_logs

# ChromaDB Client
chroma_client = chromadb.HttpClient(host=CHROMA_URL, port=CHROMA_PORT)
emb_fn = embedding_functions.DefaultEmbeddingFunction()
collection = chroma_client.get_or_create_collection(
    name="documents", embedding_function=emb_fn)

# Gemini Client
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-pro')

# --- Data Models ---


class ChatRequest(BaseModel):
    query: str
    selected_docs: Optional[List[str]] = []

# --- Background Task: Audit Logging ---
# We run this in the background so the user doesn't wait for the database write


async def log_to_mongo(query: str, answer: str, cache_hit: bool):
    log_entry = {
        "timestamp": datetime.utcnow(),
        "query": query,
        "answer": answer,
        "cache_hit": cache_hit
    }
    await logs_collection.insert_one(log_entry)
    print("[*] Interaction logged to MongoDB")

# --- Main Endpoint ---


@app.post("/chat")
async def chat(request: ChatRequest, background_tasks: BackgroundTasks):
    try:
        # 1. Create a unique hash for the question to use as a cache key
        query_hash = hashlib.md5(request.query.encode()).hexdigest()

        # 2. Check Garnet (Cache) first
        cached_response = await cache.get(query_hash)
        if cached_response:
            print("[+] Cache HIT in Garnet")
            answer = cached_response.decode('utf-8')
            background_tasks.add_task(
                log_to_mongo, request.query, answer, True)
            return {"answer": answer, "source": "cache"}

        print("[-] Cache MISS. Retrieving from ChromaDB...")

        # 3. Query ChromaDB for relevant document chunks
        # If the user selected specific docs in the UI, we filter by them
        where_clause = None
        if request.selected_docs:
            # Note: For multiple docs, Chroma uses a specific $in operator syntax
            if len(request.selected_docs) == 1:
                where_clause = {"source": request.selected_docs[0]}
            else:
                where_clause = {"source": {"$in": request.selected_docs}}

        results = collection.query(
            query_texts=[request.query],
            n_results=3,  # Bring back the top 3 most relevant paragraphs
            where=where_clause
        )

        # Extract the text chunks from the ChromaDB response
        retrieved_chunks = results['documents'][0] if results['documents'] else [
        ]

        if not retrieved_chunks:
            return {"answer": "I couldn't find any relevant information in your uploaded documents.", "source": "system"}

        # 4. Construct the prompt for Gemini
        context = "\n\n".join(retrieved_chunks)
        prompt = f"""
        You are a helpful assistant. Use ONLY the following retrieved context to answer the user's question. 
        If the answer is not contained in the context, say "I cannot answer this based on the provided documents."
        
        Context:
        {context}
        
        User Question: {request.query}
        """

        # 5. Call LLM
        response = model.generate_content(prompt)
        final_answer = response.text

        # 6. Save answer back to Garnet Cache (Expire after 1 hour / 3600 seconds)
        await cache.setex(query_hash, 3600, final_answer)

        # 7. Trigger background audit log
        background_tasks.add_task(
            log_to_mongo, request.query, final_answer, False)

        return {"answer": final_answer, "source": "llm", "context_used": retrieved_chunks}

    except Exception as e:
        print(f"Error: {str(e)}")
        raise HTTPException(
            status_code=500, detail="Internal Server Error during retrieval")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)
