from fastapi import FastAPI, UploadFile, File, HTTPException
from minio import Minio
import nats
import uuid
import io

app = FastAPI(title="Upload Service")

# --- Configuration ---
MINIO_URL = "localhost:9000"
MINIO_ACCESS_KEY = "admin_user"
MINIO_SECRET_KEY = "admin_password_123"
BUCKET_NAME = "raw-documents"
NATS_URL = "nats://localhost:4222"

# --- Initialize MinIO Client ---
minio_client = Minio(
    MINIO_URL,
    access_key=MINIO_ACCESS_KEY,
    secret_key=MINIO_SECRET_KEY,
    secure=False # Set to True in actual production with HTTPS
)

# Ensure the bucket exists when the app starts
if not minio_client.bucket_exists(BUCKET_NAME):
    minio_client.make_bucket(BUCKET_NAME)
    print(f"Created bucket: {BUCKET_NAME}")

@app.post("/upload")
async def upload_document(file: UploadFile = File(...)):
    # 1. Validate File Type
    if not file.filename.endswith(('.txt', '.md')):
        raise HTTPException(status_code=400, detail="Only .txt and .md files are allowed")

    try:
        # 2. Generate a unique ID for the file to prevent overwriting
        file_id = f"{uuid.uuid4()}_{file.filename}"
        
        # Read the file into memory
        file_content = await file.read()
        file_size = len(file_content)
        file_stream = io.BytesIO(file_content)

        # 3. Upload to MinIO
        minio_client.put_object(
            bucket_name=BUCKET_NAME,
            object_name=file_id,
            data=file_stream,
            length=file_size,
            content_type=file.content_type
        )

        # 4. Notify the system via NATS
        # Connect to NATS
        nc = await nats.connect(NATS_URL)
        
        # Create the message payload
        message_data = f"NEW_FILE:{file_id}".encode()
        
        # Publish the message to the 'document.uploaded' topic
        await nc.publish("document.uploaded", message_data)
        
        # Close NATS connection
        await nc.close()

        return {
            "status": "success",
            "message": "File uploaded and ingestion triggered.",
            "file_id": file_id
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)