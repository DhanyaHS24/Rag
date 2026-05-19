import os
import sys
import io
import asyncio
from typing import Optional

import nats
from minio import Minio
import chromadb
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader

from shared.embeddings import get_collection_name, embed_documents
from shared.db_logger import log_action, generate_cid


NATS_URL = os.getenv("NATS_URL", "nats://nats:4222")
MINIO_URL = os.getenv("MINIO_URL", "minio:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "admin_user")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "admin_password_123")
BUCKET_NAME = os.getenv("MINIO_BUCKET", "raw-documents")

CHROMA_URL = os.getenv("CHROMA_URL", "chromadb")
CHROMA_PORT = int(os.getenv("CHROMA_PORT", "8000"))


COLLECTION_NAME = get_collection_name("documents")

minio_client = Minio(MINIO_URL, MINIO_ACCESS_KEY,
                     MINIO_SECRET_KEY, secure=False)


def get_collection() -> chromadb.api.models.Collection.Collection:
    client = chromadb.HttpClient(host=CHROMA_URL, port=CHROMA_PORT)
    # create_collection is idempotent in practice, but we guard with get_collection.
    try:
        return client.get_collection(name=COLLECTION_NAME)
    except Exception:
        return client.create_collection(name=COLLECTION_NAME)


async def connect_nats_with_retry(max_tries: int = 30, sleep_s: float = 2.0) -> nats.aio.client.Client:
    last_exc: Optional[Exception] = None
    for _ in range(max_tries):
        try:
            return await nats.connect(NATS_URL)
        except Exception as exc:  # pragma: no cover
            last_exc = exc
            await asyncio.sleep(sleep_s)
    raise RuntimeError(f"Could not connect to NATS: {last_exc}")


def load_document_text(file_id: str) -> str:
    response = minio_client.get_object(BUCKET_NAME, file_id)
    try:
        data = response.read()
        lower = file_id.lower()

        if lower.endswith(".pdf") or ".pdf" in lower:
            reader = PdfReader(io.BytesIO(data))
            pages = [page.extract_text() or "" for page in reader.pages]
            return "\n".join(pages).strip()

        return data.decode("utf-8", errors="ignore").strip()

    finally:
        response.close()
        response.release_conn()


async def process_document(file_id: str, collection, cid: Optional[str] = None):
    corr_id = cid or generate_cid()
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

        splitter = RecursiveCharacterTextSplitter(
            chunk_size=500, chunk_overlap=50)
        chunks = splitter.split_text(content)
        if not chunks:
            raise ValueError(
                "No text chunks could be extracted from the document")

        ids = [f"{file_id}_{i}" for i in range(len(chunks))]
        metadatas = [{"source": file_id}] * len(chunks)
        embeddings = embed_documents(chunks)

        # Add is safe; Chroma will error on duplicates depending on configuration.
        # For production, you might implement delete-by-source before add.
        collection.add(
            documents=chunks,
            ids=ids,
            metadatas=metadatas,
            embeddings=embeddings,
        )

        log_action(
            service="ingestion_service",
            action="chromadb_ingested",
            payload={"file_id": file_id, "chunks_count": len(chunks)},
            correlation_id=corr_id,
            status="success",
        )

    except Exception as e:
        log_action(
            service="ingestion_service",
            action="processing_error",
            payload={"file_id": file_id, "error": str(e)},
            correlation_id=corr_id,
            status="failed",
            error=str(e),
        )
        raise


async def handler(collection, msg):
    data = msg.data.decode("utf-8")
    if not data.startswith("NEW_FILE:"):
        return

    parts = data.split(":")
    file_id = parts[1] if len(parts) > 1 else ""
    cid = parts[2] if len(parts) > 2 else None

    await process_document(file_id, collection, cid=cid)


async def main():
    collection = get_collection()
    nc = await connect_nats_with_retry()

    log_action(
        service="ingestion_service",
        action="service_started",
        payload={"nats_url": NATS_URL, "chromadb_collection": COLLECTION_NAME},
        correlation_id=generate_cid(),
        status="success",
    )

    await nc.subscribe("document.uploaded", cb=lambda msg: handler(collection, msg))

    while True:
        await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(main())
