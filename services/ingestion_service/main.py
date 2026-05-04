import asyncio
import nats
from minio import Minio
import chromadb
from langchain_text_splitters import RecursiveCharacterTextSplitter
from chromadb.utils import embedding_functions

# --- Config ---
NATS_URL = "nats://localhost:4222"
MINIO_URL = "localhost:9000"
BUCKET_NAME = "raw-documents"
CHROMA_URL = "localhost"
CHROMA_PORT = 8001

# Initialize Clients
minio_client = Minio(MINIO_URL, "admin_user", "admin_password_123", secure=False)
chroma_client = chromadb.HttpClient(host=CHROMA_URL, port=CHROMA_PORT)
# We'll use a simple, free embedding model that runs on your CPU
emb_fn = embedding_functions.DefaultEmbeddingFunction()
collection = chroma_client.get_or_create_collection(name="documents", embedding_function=emb_fn)

async def process_document(msg):
    data = msg.data.decode()
    if data.startswith("NEW_FILE:"):
        file_id = data.split(":")[1]
        print(f"[*] Received notification for: {file_id}")

        # 1. Download from MinIO
        response = minio_client.get_object(BUCKET_NAME, file_id)
        content = response.read().decode('utf-8')

        # 2. Chunking (Breaking text into manageable pieces)
        text_splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
        chunks = text_splitter.split_text(content)

        # 3. Embedding & Storing in ChromaDB
        # Chroma handles the embedding automatically via the emb_fn we provided
        ids = [f"{file_id}_{i}" for i in range(len(chunks))]
        collection.add(
            documents=chunks,
            ids=ids,
            metadatas=[{"source": file_id}] * len(chunks)
        )
        
        print(f"[+] Successfully ingested {len(chunks)} chunks for {file_id}")

async def main():
    # Connect to NATS
    nc = await nats.connect(NATS_URL)
    print(f"[!] Ingestion Service connected to NATS. Waiting for files...")

    # Subscribe to the topic
    await nc.subscribe("document.uploaded", cb=process_document)

    # Keep the service running
    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        await nc.close()

if __name__ == "__main__":
    asyncio.run(main())