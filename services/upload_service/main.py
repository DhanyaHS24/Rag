import os
import uuid
import io
import asyncio
from pathlib import Path
from typing import Optional

import nats
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from minio import Minio

from shared.db_logger import log_action, generate_cid


app = FastAPI(title="Upload Service")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


MINIO_URL = os.getenv("MINIO_URL", "minio:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "admin_user")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "admin_password_123")
BUCKET_NAME = os.getenv("MINIO_BUCKET", "raw-documents")
NATS_URL = os.getenv("NATS_URL", "nats://nats:4222")
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(25 * 1024 * 1024)))
ALLOWED_EXTENSIONS = {".txt", ".md", ".pdf"}


minio_client = Minio(
    MINIO_URL,
    access_key=MINIO_ACCESS_KEY,
    secret_key=MINIO_SECRET_KEY,
    secure=False,
)


async def _ensure_bucket_exists(max_tries: int = 30, sleep_s: float = 2.0) -> None:
    last_exc: Optional[Exception] = None
    for _ in range(max_tries):
        try:
            if not minio_client.bucket_exists(BUCKET_NAME):
                minio_client.make_bucket(BUCKET_NAME)
            return
        except Exception as exc:  # pragma: no cover
            last_exc = exc
            await asyncio.sleep(sleep_s)
    raise RuntimeError(f"Could not initialize MinIO bucket: {last_exc}")


async def _connect_nats_with_retry(max_tries: int = 30, sleep_s: float = 2.0) -> nats.aio.client.Client:
    last_exc: Optional[Exception] = None
    for _ in range(max_tries):
        try:
            return await nats.connect(NATS_URL)
        except Exception as exc:  # pragma: no cover
            last_exc = exc
            await asyncio.sleep(sleep_s)
    raise RuntimeError(f"Could not connect to NATS: {last_exc}")


@app.on_event("startup")
async def startup_event():
    await _ensure_bucket_exists()


@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.post("/upload")
async def upload_document(file: UploadFile = File(...)):
    cid = generate_cid()

    original_name = Path(file.filename or "document.txt").name
    suffix = Path(original_name).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        log_action(
            service="upload_service",
            action="upload_rejected",
            payload={"filename": original_name, "reason": "invalid_extension"},
            correlation_id=cid,
            status="failed",
        )
        raise HTTPException(
            status_code=400, detail="Only .txt, .md, and .pdf files are allowed")

    file_id = f"{uuid.uuid4()}_{original_name}"

    try:
        content = await file.read()
        length = len(content)
        if length == 0:
            raise HTTPException(status_code=400, detail="Uploaded file is empty")
        if length > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="Uploaded file is too large")

        file_stream = io.BytesIO(content)
        minio_client.put_object(
            bucket_name=BUCKET_NAME,
            object_name=file_id,
            data=file_stream,
            length=length,
            content_type=file.content_type or "application/octet-stream",
        )

        log_action(
            service="upload_service",
            action="file_uploaded",
            payload={
                "file_id": file_id,
                "filename": original_name,
                "size": length,
                "bucket": BUCKET_NAME,
            },
            correlation_id=cid,
            status="success",
        )

    except Exception as e:
        if isinstance(e, HTTPException):
            raise
        log_action(
            service="upload_service",
            action="upload_error",
            payload={"filename": original_name,
                     "file_id": file_id, "error": str(e)},
            correlation_id=cid,
            status="failed",
            error=str(e),
        )
        raise HTTPException(status_code=500, detail=str(e))

    # Trigger ingestion
    nc = None
    try:
        nc = await _connect_nats_with_retry()
        message_data = f"NEW_FILE:{file_id}:{cid}".encode("utf-8")
        await nc.publish("document.uploaded", message_data)

        log_action(
            service="upload_service",
            action="nats_published",
            payload={
                "channel": "document.uploaded",
                "message": message_data.decode("utf-8"),
            },
            correlation_id=cid,
            status="success",
        )
        ingestion_triggered = True
        ingestion_error = None

    except Exception as e:
        ingestion_triggered = False
        ingestion_error = str(e)
        log_action(
            service="upload_service",
            action="nats_publish_failed",
            payload={
                "channel": "document.uploaded",
                "message": f"NEW_FILE:{file_id}:{cid}",
                "error": ingestion_error,
            },
            correlation_id=cid,
            status="failed",
            error=ingestion_error,
        )

    finally:
        if nc is not None:
            await nc.close()

    resp = {
        "status": "success",
        "message": "File uploaded.",
        "file_id": file_id,
        "correlation_id": cid,
        "ingestion_triggered": ingestion_triggered,
    }
    if ingestion_error:
        resp["warning"] = "File uploaded, but ingestion trigger failed."
    return resp


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
