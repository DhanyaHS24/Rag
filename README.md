# RAG Microservices

Production-oriented local deployment for a document RAG app with:

- Streamlit frontend
- FastAPI upload, retrieval, and user services
- NATS event bus
- MinIO object storage
- ChromaDB vector store
- MongoDB audit/user storage
- Garnet Redis-compatible cache

## Run With Docker

1. Copy the environment template:

   ```powershell
   Copy-Item .env.example .env
   ```

2. Edit `.env` and change `MINIO_ROOT_PASSWORD`. Add `GEMINI_API_KEY` if you want LLM answers. Without it, the pipeline still runs with local embeddings and a safe fallback answer.

3. Build and start everything:

   ```powershell
   docker compose up --build
   ```

4. Open the app:

   - Frontend: http://localhost:8502
   - Upload API: http://localhost:8004/docs
   - Retrieval API: http://localhost:8005/docs
   - User API: http://localhost:8003/docs
   - MinIO console: http://localhost:9001

## First Use

Create an account from the frontend sign-up tab, upload a `.txt`, `.md`, or `.pdf` file, select it in the source list, then ask a question.

Ingestion happens asynchronously through NATS. If a document was just uploaded, wait a few seconds before asking questions about it.

## Useful Commands

```powershell
docker compose ps
docker compose logs -f upload_service ingestion_service retrieval_service
docker compose down
docker compose down -v
```

`docker compose down -v` deletes stored documents, vectors, users, logs, and cache data.

## Notes

- Default embeddings are local deterministic vectors so the system can run without an external API.
- Set `GEMINI_API_KEY` and keep `EMBEDDING_BACKEND` unset or non-local if you want Gemini embeddings.
- Do not commit `.env`; it is intentionally ignored.
