from shared.embeddings import get_collection_name
from shared.embeddings import embed_documents
from shared.db_logger import log_action, generate_cid
import asyncio
import nats
from minio import Minio
import chromadb
from langchain_text_splitters import RecursiveCharacterTextSplitter
import requests
import time
import sys
import os
import io
from typing import List
from pypdf import PdfReader

sys.path.insert(0, os.path.join(os.path.dirname(file), ".."))

MONGO_URL_ENV = os.getenv("MONGO_URL", "mongodb://mongodb:27017")
NATS_URL = os.getenv("NATS_URL", "nats://nats:4222")
MINIO_URL = os.getenv("MINIO_URL", "minio:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "admin_user")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "admin_password_123")
BUCKET_NAME = "raw-documents"
CHROMA_URL = os.getenv("CHROMA_URL", "chromadb")
CHROMA_PORT = int(os.getenv("CHROMA_PORT", 8000))
COLLECTION_NAME = get_collection_name()

minio_client = Minio(MINIO_URL, MINIO_ACCESS_KEY,
                     MINIO_SECRET_KEY, secure=False)


async def connect_nats_with_retry():
last_error = None
for _ in range(30):
try:
return await nats.connect(NATS_URL)
except Exception as exc:
last_error = exc
print(f"[!] Waiting for NATS... {exc}", file=sys.stderr)
await asyncio.sleep(2)
raise RuntimeError(f"Could not connect to NATS: {last_error}")


def get_collection():


chroma_client = chromadb.HttpClient(host=CHROMA_URL, port=CHROMA_PORT)
for _ in range(30):
try:
try:
collection = chroma_client.get_collection(name=COLLECTION_NAME)
return collection
except Exception as e:
if "does not exist" in str(e).lower():
return chroma_client.create_collection(name=COLLECTION_NAME)
raise
except Exception as e:
print(f"[!] Waiting for ChromaDB... {e}", file=sys.stderr)
time.sleep(2)
raise Exception("Could not connect to ChromaDB")


def load_document_text(file_id: str) -> str:


response = minio_client.get_object(BUCKET_NAME, file_id)
try:
if file_id.lower().endswith(".pdf") or ".pdf" in file_id.lower():
reader = PdfReader(io.BytesIO(response.read()))
pages = [page.extract_text() or "" for page in reader.pages]
return "\n".join(pages).strip()

raw_bytes = response.read()
return raw_bytes.decode("utf-8", errors="ignore").strip()
finally:
    response.close()
    response.release_conn()


async def process_document(file_id: str, collection, cid: str = None):
corr_id = cid or generate_cid()
print(f"[*] Processing: {file_id}", file=sys.stderr)

log_action(
    service="ingestion_service",
    action="processing_started",
    payload={"file_id": file_id},
    correlation_id=corr_id,
    status="started",
)

try:
    content = load_document_text(file_id)
    if not content:
        raise ValueError("Document content is empty after extraction")
    print(f"[*] Downloaded content ({len(content)} chars)", file=sys.stderr)

    log_action(
        service="ingestion_service",
        action="minio_downloaded",
        payload={"file_id": file_id, "content_length": len(content)},
        correlation_id=corr_id,
        status="success",
    )

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=500, chunk_overlap=100)
    chunks = splitter.split_text(content)
    if not chunks:
        raise ValueError("No text chunks could be extracted from the document")
    print(f"[*] Split into {len(chunks)} chunks", file=sys.stderr)

    ids = [f"{file_id}_{i}" for i in range(len(chunks))]
    metadatas = [{"source": file_id} for _ in chunks]
    embeddings = embed_documents(chunks)

    collection.add(
        documents=chunks,
        ids=ids,
        metadatas=metadatas,
        embeddings=embeddings,
    )
    print(f"[+] Ingested {len(chunks)} chunks", file=sys.stderr)

    log_action(
        service="ingestion_service",
        action="chromadb_ingested",
        payload={
            "file_id": file_id,
            "chunks_count": len(chunks),
            "chunk_ids": ids[:5],
        },
        correlation_id=corr_id,
        status="success",
    )

except Exception as e:
    import traceback

    print(f"[!] Error: {e}", file=sys.stderr)
    traceback.print_exc()

    log_action(
        service="ingestion_service",
        action="processing_error",
        payload={"file_id": file_id, "error": str(e)},
        correlation_id=corr_id,
        status="failed",
        error=str(e),
    )


async def main():
nc = await connect_nats_with_retry()
print("[!] Ingestion Service started", file=sys.stderr)
print("[*] Waiting for ChromaDB to be ready...", file=sys.stderr)
collection = get_collection()
print("[+] ChromaDB collection ready", file=sys.stderr)

log_action(
    service="ingestion_service",
    action="service_started",
    payload={"nats_url": NATS_URL, "chromadb_ready": True},
    status="success",
)


async def handler(msg):
    data = msg.data.decode()
    if data.startswith("NEW_FILE:"):
        parts = data.split(":")
        file_id = parts[1] if len(parts) > 1 else ""
        cid = parts[2] if len(parts) > 2 else None
        await process_document(file_id, collection, cid)

        log_action(
            service="ingestion_service",
            action="nats_message_received",
            payload={"channel": "document.uploaded", "file_id": file_id},
            correlation_id=cid,
            status="success",
        )

sub = await nc.subscribe("document.uploaded", cb=handler)
print("[*] Subscribed to document.uploaded", file=sys.stderr)

print("[*] Waiting for messages...", file=sys.stderr)
while True:
    try:
        await asyncio.sleep(1)
    except asyncio.CancelledError:
        break

await nc.drain()
await nc.close()

if name == "main":
asyncio.run(main())
