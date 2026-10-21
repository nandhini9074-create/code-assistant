# RepoLens — AI Code Search Assistant

> **Semantic code intelligence for any GitHub repository or ZIP upload.**
> Ask questions, find bugs, suggest features, optimize code, and audit for vulnerabilities — all powered by vector search and an LLM pipeline.

---

## Table of Contents

1. [Why RepoLens?](#-why-repolens)
2. [Features](#-features)
3. [Architecture](#-architecture)
4. [How the App Works](#-how-the-app-works)
5. [Tech Stack](#-tech-stack)
6. [Prerequisites](#-prerequisites)
7. [Installation & Setup](#-installation--setup)
8. [Environment Variables](#-environment-variables)
9. [Running the App](#-running-the-app)
10. [Evaluation Framework](#-evaluation-framework)
11. [Project Structure](#-project-structure)
12. [Testing](#-testing)

---

## 🚀 Why RepoLens?

Modern codebases are too large to grep, too complex to manually review, and too dynamic for static documentation to stay current. RepoLens bridges that gap by:

- **Understanding intent** — it knows whether you want to *find*, *fix*.
- **Searching semantically** — exact keyword matches miss synonyms and related concepts; vector search does not.
- **Generating grounded answers** — every response is anchored to real code chunks retrieved from your repo, not hallucinated.
- **Running offline** — bring your own GitHub repo or upload a ZIP; no external code indexing service required.
- **Staying evaluable** — a built-in evaluation framework lets you measure and track retrieval and intent quality over time.

---

## ✨ Features

| Feature | Description |
|---|---|
| **Semantic Code Search** | Hybrid dense + sparse vector search over code chunks stored in Qdrant |
| **Intent Classification** | Automatically classifies queries into 6 intents: `RETRIEVE`, `ADD_FEATURE`, `FIX_BUG`, 'FIX_VULNERABILITY` |
| **GitHub Integration** | Index any public or private GitHub repository via URL; auto-update via webhooks on push |
| **ZIP Upload** | Upload a local repository as a ZIP archive for offline or private repo analysis |
| **Vulnerability Scanning** | Dedicated pipeline stage for security analysis with LLM-assisted remediation suggestions |
| **Code Change Suggestions** | For `ADD_FEATURE`, `FIX_BUG`, 
| **Evidence Validation** | Validates retrieved chunks against the query before synthesis to prevent hallucination |
| **Background Job Processing** | Ingestion runs as async Celery tasks; job status is trackable through the UI |
| **Evaluation Framework** | Offline evaluation of retrieval (Precision@K, Recall@K, MRR, nDCG@K) and intent classification (accuracy, F1, confusion matrix) |
| **React Frontend** | Clean, responsive UI with search, repository management, upload, and job monitoring pages |

---

## 🏗 Architecture

![RepoLens system architecture](backend/docs/architecture.svg)

The diagram shows the major components and how repository ingestion, search, and vulnerability analysis use the API, workers, databases, and AI integrations.

### Data Flow

```
User Query
    │
    ▼
Intent Classification  ────► RETRIEVE / FIX_BUG / ADD_FEATURE
    │                          FIX_VULNERABILITY
    ▼
Code Retrieval  (Qdrant hybrid search)
    │
    ▼
Evidence Validation  (filter low-quality chunks)
    │
    ▼
Context Builder  (assemble prompt context)
    │
    ├── RETRIEVE          → Response Generation (direct answer)
    ├── FIX_BUG           → Code Analysis → Patch → Remediation Verification
    ├── ADD_FEATURE       → Change Planning → Patch → Suggestion Validation
    └── FIX_VULNERABILITY → Vulnerability Orchestration → Remediation Verification
    │
    ▼
Structured JSON Response → Frontend rendering
```

---

## ⚙️ How the App Works

### 1. Repository Ingestion

**GitHub repos:**
Submit a repo URL → the backend fetches files via the GitHub API → files are filtered by language and size → code is parsed into AST-aware chunks → chunks are embedded using Jina AI → vectors are upserted into a per-repository Qdrant collection.

**ZIP upload:**
Upload a `.zip` → backend extracts, filters, chunks, embeds, and upserts the same way — no GitHub token required.

**Webhooks:**
Register a GitHub webhook → on every push, changed files are re-ingested incrementally using SHA-based checkpointing (only modified or deleted files are re-processed).

### 2. Search & Query Answering

1. **Query preprocessing** — normalises whitespace, expands abbreviations.
2. **Intent classification** — routes the query to one of 6 intents using the LLM.
3. **Collection selection** — picks the correct Qdrant collection for the target repository.
4. **Hybrid retrieval** — combines dense (semantic) and sparse (keyword) vectors, returning top-K chunks.
5. **Evidence validation** — scores each chunk for relevance; low-confidence chunks are dropped.
6. **Response generation** — LLM synthesizes a grounded answer from the validated chunks.
7. For non-RETRIEVE intents, additional stages plan changes, generate patches, and verify correctness.

### 3. Background Jobs

Long ingestion tasks run as Celery workers backed by Redis. The **Jobs** page in the frontend polls job status in real time, showing progress, errors, and completion.

---

## 🛠 Tech Stack

### Backend

| Layer | Technology |
|---|---|
| Web framework | FastAPI + Uvicorn |
| Task queue | Celery + Redis |
| Database | PostgreSQL + SQLAlchemy (async) + Alembic |
| Vector store | Qdrant |
| Embeddings | Jina AI `jina-embeddings-v3` (1024-dim) |
| LLM | Qwen `qwen-plus` (DashScope, OpenAI-compatible API) |
| Code chunking | AST-aware chunker (Python, JS, TS, and more) |
| Language | Python 3.11+ |

### Frontend

| Layer | Technology |
|---|---|
| Framework | React 19 + TypeScript |
| Build tool | Vite 8 |
| UI library | MUI (Material UI) v9 |
| HTTP client | Axios |
| Markdown | react-markdown + react-syntax-highlighter |
| Routing | React Router v7 |

---

## 📋 Prerequisites

- **Python 3.11+**
- **Node.js 18+** and npm
- **PostgreSQL 14+**
- **Redis 7+**
- **Qdrant** (Docker or Qdrant Cloud)
- **Jina AI API key** — [console.jina.ai](https://console.jina.ai)
- **Qwen / DashScope API key** — [dashscope.console.aliyun.com](https://dashscope.console.aliyun.com)
- **GitHub Personal Access Token** (optional, for private repos and webhooks)

### Quick-start infrastructure with Docker

```bash
# Qdrant vector database
docker run -d --name qdrant -p 6333:6333 qdrant/qdrant

# Redis (broker + cache)
docker run -d --name redis -p 6379:6379 redis:7-alpine

# PostgreSQL
docker run -d --name postgres \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=code_explorer \
  -p 5432:5432 postgres:16-alpine
```

---

## 🔧 Installation & Setup

### 1. Clone the repository

```bash
git clone https://github.com/your-org/repolens.git
cd repolens/code-assistant
```

### 2. Backend setup

```bash
cd backend

# Create and activate virtual environment
python -m venv venv

# Windows
venv\Scripts\activate
# macOS / Linux
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Configure environment variables

```bash
cp .env.example .env
# Open .env and fill in all required values
```

### 4. Run database migrations

```bash
alembic upgrade head
```

### 5. Frontend setup

```bash
cd ../frontend
npm install
```

---

## 🌍 Environment Variables

| Variable | Description | Required |
|---|---|---|
| `DATABASE_URL` | PostgreSQL connection string | ✅ |
| `QDRANT_URL` | Qdrant URL (default: `http://localhost:6333`) | ✅ |
| `REDIS_URL` | Redis URL (default: `redis://localhost:6379/0`) | ✅ |
| `CELERY_BROKER_URL` | Celery broker URL | ✅ |
| `JINA_API_KEY` | Jina AI API key for embeddings | ✅ |
| `QWEN_API_KEY` | DashScope API key for Qwen LLM | ✅ |
| `GITHUB_TOKEN` | GitHub Personal Access Token | Private repos |
| `GITHUB_WEBHOOK_SECRET` | Shared secret for webhook HMAC validation | Webhooks |
| `APP_BASE_URL` | Publicly reachable URL for webhook callbacks | Webhooks |

See `backend/.env.example` for the full list with defaults and descriptions.

---

## ▶️ Running the App

### Backend API

```bash
cd backend
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

API docs: [http://localhost:8000/docs](http://localhost:8000/docs)

### Celery worker

```bash
cd backend
celery -A app.workers.celery_app worker --loglevel=info
```

### Frontend

```bash
cd frontend
npm run dev
```

Frontend: [http://localhost:5173](http://localhost:5173)

---

## 📊 Evaluation Framework

`backend/evaluation/` is a standalone module for measuring retrieval and intent quality — completely separate from production code.

### Dataset format (JSONL)

```jsonl
{
  "query_id": "q01",
  "query": "Where is the appointment time suggestion implemented?",
  "expected_intent": "RETRIEVE",
  "collection_name": "repo_myorg_hospital_management",
  "expected_chunks": [
    {"file_path": "app/routers/appointments.py", "symbol_name": "suggest_time", "relevance_grade": 3.0},
    {"file_path": "app/crud/appointment.py", "symbol_name": "find_nearest_available_slot", "relevance_grade": 2.0}
  ]
}
```

Chunks can use `chunk_id` for backward compatibility, or `file_path` + `symbol_name` as the identity key.

### Run evaluation

```bash
cd backend

# Offline (intent only, no Qdrant required)
python -m evaluation.cli suite evaluation/datasets/sample_evaluation_dataset.jsonl --offline

# Full (retrieval + intent, Qdrant must be running)
python -m evaluation.cli suite evaluation/datasets/sample_evaluation_dataset.jsonl
```

### Metrics

| Category | Metrics |
|---|---|
| Retrieval | Precision@K, Recall@K, MRR, nDCG@K |
| Intent | Accuracy, per-class Precision/Recall/F1, Macro-F1, Confusion Matrix |

Results are written as versioned JSON and a Markdown report. The suite exits with a non-zero code when any metric falls below its configured threshold.

---

## 📁 Project Structure

```
code-assistant/
├── backend/
│   ├── app/
│   │   ├── api/v1/           # FastAPI route handlers
│   │   ├── config.py         # Pydantic settings (loaded from .env)
│   │   ├── core/             # Logging, middleware, enums
│   │   ├── dependencies.py   # FastAPI dependency injection
│   │   ├── infrastructure/   # DB, Qdrant, Redis clients
│   │   ├── main.py           # App factory + lifespan manager
│   │   ├── modules/
│   │   │   ├── code_analysis/    # Vulnerability analysis, analyzers
│   │   │   ├── embedding/        # Jina AI embedding client
│   │   │   ├── ingestion/        # Ingestion pipeline (14 stages)
│   │   │   ├── llm/              # Qwen LLM client
│   │   │   ├── repositories/     # Repository CRUD & domain
│   │   │   ├── search/           # Search pipeline (21 stages)
│   │   │   └── webhooks/         # GitHub webhook handler
│   │   └── workers/          # Celery app & task definitions
│   ├── evaluation/           # Offline evaluation framework
│   │   ├── adapters/         # Retriever & intent adapters
│   │   ├── datasets/         # Sample evaluation datasets
│   │   ├── cli.py            # Evaluation CLI
│   │   ├── dataset.py        # Loader & validator
│   │   ├── metrics.py        # Precision, Recall, MRR, nDCG
│   │   ├── runner.py         # EvaluationRunner
│   │   ├── reporting.py      # Markdown & JSON reports
│   │   ├── schemas.py        # Dataset schema (Pydantic v2)
│   │   ├── suite.py          # Suite orchestration
│   │   └── thresholds.py     # Pass/fail thresholds
│   ├── migrations/           # Alembic DB migrations
│   ├── tests/
│   │   └── unit/evaluation/  # 165 evaluation unit tests
│   ├── .env.example
│   └── pyproject.toml
└── frontend/
    ├── src/
    │   ├── api/              # Axios API client
    │   ├── components/       # Shared UI components
    │   ├── pages/
    │   │   ├── SearchPage.tsx        # Main search interface
    │   │   ├── RepositoriesPage.tsx  # Repository management
    │   │   ├── UploadPage.tsx        # ZIP upload
    │   │   ├── JobsPage.tsx          # Background job monitor
    │   │   └── HealthPage.tsx        # System health
    │   └── App.tsx
    └── package.json
```

---

## 🧪 Testing

```bash
cd backend

# All unit tests
pytest tests/unit/ -v

# Evaluation tests only
pytest tests/unit/evaluation/ -v

# With coverage
pytest tests/unit/ --cov=app --cov=evaluation --cov-report=term-missing
```

Current evaluation test suite: **165 tests, 0 failures**.

---

## 📄 License

MIT — see [LICENSE](LICENSE).
