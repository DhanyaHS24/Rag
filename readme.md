RAG Microservices Project
A Retrieval-Augmented Generation (RAG) system built with microservices architecture. This application allows users to upload documents, process them into chunks, store them in a vector database, and chat with the documents using an LLM.

Overview
This project implements a complete RAG pipeline:

Upload documents (.txt, .md, .pdf files)
Process documents into chunks and store in vector database
Chat with documents using LLM-powered retrieval
Architecture Diagram
┌─────────────────────────────────────────────────────────────────────────────────┐
│ RAG MICROSERVICES SYSTEM │
├─────────────────────────────────────────────────────────────────────────────────┤
│ │
│ USER ──────▶ FRONTEND ──────▶ UPLOAD ──────▶ MINIO (Storage) │
│ │ (Streamlit) Service │ │
│ │ │ │ │ │
│ │ │ ▼ │ │
│ │ │ NATS (Message Broker) │
│ │ │ │ │ │
│ │ │ ▼ │ │
│ │ │ INGESTION ───────┘ │
│ │ │ Service │
│ │ │ │ │
│ │ │ ▼ │
│ │ │ CHROMADB (Vector DB) │
│ │ │ ▲ │
│ │ │ │ │
│ │ │ RETRIEVAL ◀──── USER QUERY │
│ │ │ Service │ │
│ │ │ │ │ │
│ │ │ ▼ │ │
│ │ │ GEMINI (LLM) ─────────────────┘ │
│ │ │ + MOCK FALLBACK │
│ │ ▼ │
│ ◀───── ANSWER + SOURCES │
│ │
└─────────────────────────────────────────────────────────────────────────────────┘
API Reference

1. Upload Service (Port 8000)
   Base URL: http://localhost:8000

Method Endpoint Description Request Body Response
POST /upload Upload document multipart/form-data with file field {"status": "success", "message": "...", "file_id": "..."}
GET /health Health check - {"status": "healthy"}
Example:

curl -X POST http://localhost:8000/upload -F "file=@document.txt" 2. Retrieval Service (Port 8002)
Base URL: http://localhost:8002

Method Endpoint Description Request Body Response
POST /chat Query documents {"query": "...", "selected_docs": [...]} {"answer": "..."}
GET /health Health check - {"status": "healthy"}
Example:

curl -X POST http://localhost:8002/chat \
-H "Content-Type: application/json" \
-d '{"query": "What is the document about?", "selected_docs": ["file.txt"]}' 3. Infrastructure APIs
These services listen on the listed container ports inside Docker. By default, only the frontend is published to the host; the backend services talk to each other over the Docker network to avoid local port conflicts.

Service Port URL Purpose
Frontend (Streamlit) 8502 http://localhost:8502 User interface
MinIO API 9000 http://localhost:9000 S3-compatible storage
MinIO Console 9001 http://localhost:9001 Web UI for MinIO
ChromaDB 8001 http://localhost:8001 Vector database API
NATS 4222 nats://localhost:4222 Message broker
NATS Monitor 8222 http://localhost:8222 NATS monitoring 4. All APIs Summary

Service Endpoint Method Purpose

1 Upload Service /upload POST Upload documents
2 Upload Service /health GET Health check
3 Retrieval Service /chat POST Query RAG system
4 Retrieval Service /health GET Health check
5 MinIO /_ Various Object storage operations
6 ChromaDB /api/v2/_ Various Vector DB operations
7 MongoDB mongodb://localhost:27018 - Document metadata storage
Technology Stack - Why These Choices?
Why Docker & Docker Compose?
Alternative Why Docker is Better
Kubernetes Overkill for development; too complex
VMs Heavy; slow to start; resource-intensive
Bare metal No isolation; hard to reproduce
Docker Compose ✅ Lightweight; easy to define multi-service apps; perfect for local dev
Why FastAPI for Services?
Alternative Why FastAPI is Better
Flask No built-in validation; manual docs
Django Too heavy for microservices; too much magic
Node.js/Express Python is better for ML/AI libraries
FastAPI ✅ Auto-generated OpenAPI docs; Pydantic validation; async; type safety
Why MinIO instead of AWS S3?
Alternative Why MinIO is Better
AWS S3 Costs money; requires internet; external dependency
Azure Blob Vendor lock-in; complex setup
Google Cloud Storage Vendor lock-in; costs money
Local filesystem No API; can't scale
MinIO ✅ S3-compatible; runs locally; same API; easy to switch to real S3 later
Why ChromaDB instead of other vector DBs?
Alternative Why ChromaDB is Better
Pinecone Costs money; external service; no local option
Weaviate Heavy; complex setup; more features than needed
Qdrant Rust-based; harder to debug; less Python-native
pgvector Requires PostgreSQL; adds complexity
FAISS No server mode; no filtering; complex
ChromaDB ✅ Built for RAG; Python-native; simple API; embeddings included; easy to use
Why NATS instead of RabbitMQ/Kafka?
Alternative Why NATS is Better
RabbitMQ Heavy; complex exchanges; harder to scale
Apache Kafka Overkill; needs Zookeeper; complex setup; high resource usage
Redis Pub/Sub No persistence; no guarantees; fire-and-forget
NATS ✅ Lightweight; 10x performance; JetStream for persistence; simple subjects
Why MongoDB instead of PostgreSQL?
Alternative Why MongoDB is Better
PostgreSQL Schema rigidity; requires migrations; document model harder
MySQL Same as PostgreSQL; less flexible
SQLite No network access; not for production
MongoDB ✅ Document storage; flexible schema; perfect for metadata; easy to scale
Why Google Gemini instead of OpenAI?
Alternative Why Gemini is Better
OpenAI GPT-4 Costs money; rate limits; requires account approval
Claude Less context for code; rate limits
Llama (local) Requires GPU; slow; resource-heavy
Gemini ✅ Free tier available; good performance; easy API; generous rate limits
Why Microsoft Garnet instead of Redis?
Alternative Why Garnet is Better
Redis Good but proprietary; performance limits
Dragonfly Less mature; fewer clients
KeyDB Less community support
Garnet ✅ Microsoft open-source; Redis-compatible API; higher throughput; better scalability; modern architecture
Note: Garnet is fully Redis-compatible, so it uses the same client libraries and port 6379.

Why Streamlit for Frontend?
Alternative Why Streamlit is Better
React/Vue More code; need frontend developer
Flask templates Ugly; complex for interactive UI
Django Overkill; too much boilerplate
Streamlit ✅ Python-only; rapid prototyping; built for ML/AI apps; interactive widgets
Why LangChain for Text Splitting?
Alternative Why LangChain is Better
Manual splitting Naive; loses context; no smart splitting
NLTK/spaCy Lower-level; more code needed
LangChain Text Splitters ✅ Optimized for RAG; preserves semantic chunks; configurable
Data Flow
Flow 1: Document Upload & Processing

1. User uploads file via Frontend (Streamlit)
   ↓

2. Frontend → Upload Service (POST /upload)
   ↓

3. Upload Service → MinIO (S3 storage)
   ↓

4. Upload Service → NATS (publish "NEW_FILE:{file_id}:{correlation_id}")
   ↓

5. Ingestion Service (subscribed to NATS) receives message
   ↓

6. Ingestion Service → MinIO (download file)
   ↓

7. Ingestion Service splits text into chunks (500 chars, 50 overlap)
   ↓

8. Ingestion Service → ChromaDB (store embeddings + chunks)
   Flow 2: User Query (RAG)

9. User asks question via Frontend
   ↓

10. Frontend → Retrieval Service (POST /chat)
    ↓

11. Retrieval Service → ChromaDB (semantic search)
    ↓

12. ChromaDB returns relevant chunks
    ↓

13. Retrieval Service → Gemini API (generate answer)
    ↓

14. Frontend displays answer + sources
    Services
    Service Port Description
    Frontend 8502 Streamlit chat UI
    Upload Service 8000 File upload to MinIO
    Retrieval Service 8002 RAG chat endpoint
    MinIO Console 9001 S3 storage UI
    ChromaDB 8001 Vector database
    MongoDB 27017 Document metadata
    Redis/Garnet 6379 Cache layer
    NATS 4222 Message broker
    Prerequisites
    Docker & Docker Compose
    Docker daemon running locally
    Gemini API Key (optional, for real LLM responses)
    Quick Start

15. Start all services

docker compose up -d --build

2. Check services are running

docker compose ps

3. Access the frontend at http://localhost:8502

Login: admin / admin123 (or testuser / 1234)

4. Upload a .txt, .md, or .pdf file and start chatting!

Environment Variables
Create a .env file or use the default values:

MinIO Configuration

MINIO_ROOT_USER=admin_user
MINIO_ROOT_PASSWORD=admin_password_123

NATS Configuration

NATS_URL=nats://nats:4222

ChromaDB Configuration

CHROMA_URL=chroma
CHROMA_PORT=8000

MongoDB Configuration

MONGO_URL=mongodb://mongodb:27017

Redis Configuration

GARNET_URL=garnet:6379

Gemini API Key (Get from https://ai.google.dev/)

GEMINI_API_KEY=your_api_key_here
Usage
Using the Frontend
Open http://localhost:8502
Login with credentials (admin/admin123 or testuser/1234)
Upload a .txt, .md, or .pdf file using the sidebar
Select documents to chat with
Ask questions about your documents
Using the API Directly

Upload a file

curl -X POST http://localhost:8000/upload \
-F "file=@test.txt"

Chat with documents

curl -X POST http://localhost:8002/chat \
-H "Content-Type: application/json" \
-d '{"query": "what is in the document?", "selected_docs": ["test.txt"]}'
How It Works

1. Upload Service (Port 8000)
   Accepts file uploads (.txt, .md, .pdf)
   Stores files in MinIO object storage
   Publishes a message to NATS to notify ingestion service

2. Ingestion Service
   Subscribes to NATS for new file notifications
   Downloads file from MinIO
   Splits document into chunks using LangChain's RecursiveCharacterTextSplitter
   Stores chunks in ChromaDB vector database

3. Retrieval Service (Port 8002)
   Receives user queries
   Retrieves relevant chunks from ChromaDB based on semantic similarity
   Uses Google Gemini to generate context-aware answers
   Falls back to mock responses if no API key provided

4. Frontend (Port 8502)
   Streamlit-based web interface
   User authentication (mocked)
   File upload UI
   Chat interface with history
   Commands

View all logs

docker compose logs -f

View specific service logs

docker compose logs -f upload_service

Stop all services

docker compose down

Stop and remove volumes

docker compose down -v

Rebuild a specific service

docker compose up -d --build upload_service
Documentation
Architecture - System architecture and design
API Reference - API endpoints documentation
Project Structure
rag_microservices/
├── docker-compose.yml # Docker Compose configuration
├── .env # Environment variables
├── frontend/
│ ├── app.py # Streamlit frontend app
│ └── Dockerfile # Frontend container
├── services/
│ ├── upload_service/
│ │ ├── main.py # FastAPI upload service
│ │ ├── requirements.txt
│ │ └── Dockerfile
│ ├── ingestion_service/
│ │ ├── main.py # Document ingestion worker
│ │ ├── requirements.txt
│ │ └── Dockerfile
│ └── retrieval_service/
│ ├── main.py # FastAPI retrieval API
│ ├── rag_engine.py # RAG logic (retrieval + generation)
│ ├── requirements.txt
│ └── Dockerfile
└── infra/ # Infrastructure configs
├── nats-server.conf
├── mongo-init.js
└── minio-config
Troubleshooting
Services won't start

Check logs

docker compose logs

Verify ports are not in use

docker compose ps
No API key set
The system works without a Gemini API key but uses mock responses. Set GEMINI_API_KEY in .env for real LLM-powered responses.

Can't connect to services
Ensure all services are running:

docker compose ps
