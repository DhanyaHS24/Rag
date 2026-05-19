import uvicorn
from shared.db_logger import log_action, generate_cid
import asyncio
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from minio import Minio
import nats
import uuid
import io
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(file), ".."))

app = FastAPI(title="Upload Service")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[""],
    allow_credentials=False,
    allow_methods=[""],
    allow_headers=["*"],
)

MINIO_URL = os.getenv("MINIO_URL", "minio:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "admin_user")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "admin_password_123")
BUCKET_NAME = "raw-documents"
NATS_URL = os.getenv("NATS_URL", "nats://nats:4222")

minio_client = Minio(
    MINIO_URL, access_key=MINIO_ACCESS_KEY, secret_key=MINIO_SECRET_KEY, secure=False
)


def ensure_bucket_ready():


last_error = None
for _ in range(30):
try:
if not minio_client.bucket_exists(BUCKET_NAME):
minio_client.make_bucket(BUCKET_NAME)
print(f"Created bucket: {BUCKET_NAME}")
return
except Exception as exc:
last_error = exc
print(f"Waiting for MinIO... {exc}")
time.sleep(2)
raise RuntimeError(f"Could not connect to MinIO: {last_error}")


async def connect_nats_with_retry():
last_error = None
for _ in range(30):
try:
return await nats.connect(NATS_URL)
except Exception as exc:
last_error = exc
print(f"Waiting for NATS... {exc}")
await asyncio.sleep(2)
raise RuntimeError(f"Could not connect to NATS: {last_error}")


@app.on_event("startup")
async def startup_event():
ensure_bucket_ready()


@app.get("/health")
async def health():
return {"status": "healthy"}


@app.post("/upload")
async def upload_document(file: UploadFile = File(...)):
cid = generate_cid()
filename = (file.filename or "").lower()

# TODO : file formats to be updated
if file.filename and not filename.endswith((".txt", ".md", ".pdf")):
    log_action(
        service="upload_service",
        action="upload_rejected",
        payload={"filename": file.filename, "reason": "invalid_extension"},
        correlation_id=cid,
        status="failed",
    )
    raise HTTPException(
        status_code=400, detail="Only .txt, .md, and .pdf files are allowed"
    )

file_id = f"{uuid.uuid4()}_{file.filename or 'unknown'}"

try:
    file_content = await file.read()
    file_size = len(file_content)
    file_stream = io.BytesIO(file_content)

    minio_client.put_object(
        bucket_name=BUCKET_NAME,
        object_name=file_id,
        data=file_stream,
        length=file_size,
        content_type=file.content_type or "application/octet-stream",
    )

    log_action(
        service="upload_service",
        action="file_uploaded",
        payload={
            "file_id": file_id,
            "filename": file.filename,
            "size": file_size,
            "bucket": BUCKET_NAME,
        },
        correlation_id=cid,
        status="success",
    )
except Exception as e:
    log_action(
        service="upload_service",
        action="upload_error",
        payload={"filename": file.filename, "error": str(e)},
        correlation_id=cid,
        status="failed",
        error=str(e),
    )
    raise HTTPException(status_code=500, detail=str(e))

ingestion_triggered = False
ingestion_error = None
nc = None

try:
    nc = await connect_nats_with_retry()
    message_data = f"NEW_FILE:{file_id}:{cid}".encode()
    await nc.publish("document.uploaded", message_data)
    ingestion_triggered = True

    log_action(
        service="upload_service",
        action="nats_published",
        payload={
            "channel": "document.uploaded",
            "message": f"NEW_FILE:{file_id}:{cid}",
        },
        correlation_id=cid,
        status="success",
    )
except Exception as e:
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

response = {
    "status": "success",
    "message": "File uploaded.",
    "file_id": file_id,
    "correlation_id": cid,
    "ingestion_triggered": ingestion_triggered,
}

if ingestion_error:
    response["warning"] = "File uploaded, but ingestion trigger failed."

return response

if name == "main":

uvicorn.run(app, host="0.0.0.0", port=8000)
