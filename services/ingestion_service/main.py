import os
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
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "")
BUCKET_NAME = os.getenv("MINIO_BUCKET", "raw-documents")

CHROMA_URL = os.getenv("CHROMA_URL", "chromadb")
CHROMA_PORT = int(os.getenv("CHROMA_PORT", "8000"))


COLLECTION_NAME = get_collection_name("documents")

minio_client = Minio(MINIO_URL, MINIO_ACCESS_KEY,
                     MINIO_SECRET_KEY, secure=False)


def get_collection() -> chromadb.api.models.Collection.Collection:
    client = chromadb.HttpClient(host=CHROMA_URL, port=CHROMA_PORT)
    last_exc: Optional[Exception] = None
    for _ in range(30):
        try:
            return client.get_or_create_collection(name=COLLECTION_NAME)
        except Exception as exc:
            last_exc = exc
            import time
            time.sleep(2)
    raise RuntimeError(f"Could not connect to ChromaDB: {last_exc}")


async def connect_nats_with_retry(max_tries: int = 30, sleep_s: float = 2.0) -> nats.aio.client.Client:
    last_exc: Optional[Exception] = None
    for _ in range(max_tries):
        try:
            return await nats.connect(NATS_URL)
        except Exception as exc:
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


async def process_document(file_id: str, username: str, collection, cid: Optional[str] = None):
    corr_id = cid or generate_cid()
    log_action(
        service="ingestion_service",
        action="processing_started",
        payload={"file_id": file_id, "username": username},
        correlation_id=corr_id,
        status="started",
    )

    try:
        content = await asyncio.to_thread(load_document_text, file_id)
        if not content:
            raise ValueError("Document content is empty after extraction")

        splitter = RecursiveCharacterTextSplitter(
            chunk_size=500, chunk_overlap=50)
        chunks = splitter.split_text(content)
        if not chunks:
            raise ValueError(
                "No text chunks could be extracted from the document")

        ids = [f"{file_id}_{i}" for i in range(len(chunks))]
        metadatas = [{"source": file_id, "username": username}] * len(chunks)
        embeddings = await asyncio.to_thread(embed_documents, chunks)

        try:
            await asyncio.to_thread(
                collection.delete,
                where={
                    "$and": [
                        {"source": file_id},
                        {"username": username}
                    ]
                }
            )
        except Exception as e:
            log_action(
                service="ingestion_service",
                action="delete_previous_chunks_error",
                payload={"file_id": file_id, "username": username, "error": str(e)},
                correlation_id=corr_id,
                status="warning",
            )

        await asyncio.to_thread(
            collection.add,
            documents=chunks,
            ids=ids,
            metadatas=metadatas,
            embeddings=embeddings,
        )

        log_action(
            service="ingestion_service",
            action="chromadb_ingested",
            payload={"file_id": file_id, "chunks_count": len(chunks), "username": username},
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


async def delete_document_from_chroma(file_id: str, username: str, collection, cid: str):
    log_action(
        service="ingestion_service",
        action="delete_started",
        payload={"file_id": file_id, "username": username},
        correlation_id=cid,
        status="started",
    )
    try:
        await asyncio.to_thread(
            collection.delete,
            where={
                "$and": [
                    {"source": file_id},
                    {"username": username}
                ]
            }
        )
        log_action(
            service="ingestion_service",
            action="chromadb_deleted",
            payload={"file_id": file_id, "username": username},
            correlation_id=cid,
            status="success",
        )
    except Exception as e:
        log_action(
            service="ingestion_service",
            action="delete_error",
            payload={"file_id": file_id, "error": str(e)},
            correlation_id=cid,
            status="failed",
            error=str(e),
        )
        raise


async def handler(collection, msg):
    data = msg.data.decode("utf-8")
    parts = data.split(":")
    prefix = parts[0] if parts else ""

    if prefix == "NEW_FILE":
        file_id = parts[1] if len(parts) > 1 else ""
        cid = parts[2] if len(parts) > 2 else None
        username = parts[3] if len(parts) > 3 else ""
        try:
            await process_document(file_id, username, collection, cid=cid)
        except Exception:
            pass
    elif prefix == "DELETE_FILE":
        file_id = parts[1] if len(parts) > 1 else ""
        cid = parts[2] if len(parts) > 2 else None
        username = parts[3] if len(parts) > 3 else ""
        try:
            await delete_document_from_chroma(file_id, username, collection, cid=cid or generate_cid())
        except Exception:
            pass

    try:
        await msg.ack()
    except Exception:
        pass


async def main():
    collection = get_collection()
    nc = await connect_nats_with_retry()

    js = nc.jetstream()
    stream_name = "document_events"
    subject = "document.uploaded"

    try:
        await js.add_stream(name=stream_name, subjects=[subject])
    except Exception:
        pass

    sub = await js.subscribe(subject, stream=stream_name, manual_ack=True)

    log_action(
        service="ingestion_service",
        action="service_started",
        payload={"nats_url": NATS_URL, "chromadb_collection": COLLECTION_NAME,
                 "stream": stream_name, "subject": subject},
        correlation_id=generate_cid(),
        status="success",
    )

    async for msg in sub.messages:
        task = asyncio.create_task(handler(collection, msg))
        task.add_done_callback(lambda t: t.exception() if t.exception() else None)


if __name__ == "__main__":
    asyncio.run(main())
