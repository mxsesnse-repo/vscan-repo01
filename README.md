# AI-Powered Smart CRM & Card Scanner

A complete, end-to-end CRM and networking platform that automates business card ingestion, maps professional relationships using a Knowledge Graph, tracks sales pipelines, and provides an AI-powered assistant using local Large Language Models (LLMs).

## 🚀 Key Features

* **Smart Business Card Scanner:** Automated OCR ingestion of physical business cards using Llama 3.2 Vision.
* **Knowledge Graph Engine:** Maps relationships between contacts, companies, events, domains, and sales opportunities to visualize your network.
* **Opportunity Pipeline:** Full-stack pipeline management to track deal stages (Lead, Pitching, Negotiation, Closed Won/Lost).
* **Duplicate Detection:** Automatically flags contacts with matching email or phone on approval.
* **Domain-Based Tagging:** Tag contacts by industry/domain to discover connections across your network.
* **Local AI Assistant:** A privacy-first RAG (Retrieval-Augmented Generation) chat assistant powered by Llama 3.2, capable of answering queries based on your private CRM data without sending info to the cloud.
* **Admin Dashboard:** Staff-only panel with user management, billing, ad approvals, server health metrics, and live config controls.
* **Background Processing:** Utilizes Celery and Redis to handle heavy AI/OCR tasks asynchronously without lagging the UI.

## 🛠 Tech Stack

* **Backend:** Django 5.1 (Python)
* **Database:** PostgreSQL
* **Task Queue:** Redis + Celery
* **AI/LLM:** Ollama (Llama 3.2 Vision, Llama 3.2, nomic-embed-text)
* **Frontend:** Bootstrap 5, Vanilla JavaScript
* **Vector Store:** ChromaDB
* **Payments:** Razorpay

## 📦 Prerequisites

1. **Python 3.11+**
2. **PostgreSQL**
3. **Redis**
4. **Ollama** — download from [ollama.com](https://ollama.com)

## ⚙️ Installation

### 1. Clone the repository
```bash
git clone https://github.com/Rehansh26/MSTinternship-Rehansh-Shrivastava.git
cd MSTinternship-Rehansh-Shrivastava
```

### 2. Create a virtual environment
```bash
python -m venv venv
```
Activate it:
* **Linux / macOS:** `source venv/bin/activate`
* **Windows:** `venv\Scripts\activate`

### 3. Install dependencies
```bash
pip install -r requirements.txt
```

### 4. Configure environment variables
A `.env.example` file is included with all required variable names. Copy it and fill in your values:

```bash
# Linux / macOS
cp .env.example .env

# Windows
copy .env.example .env
```

Then open `.env` and fill in your values:

```text
SECRET_KEY=your-secret-key-here
DB_NAME=crm_db
DB_USER=postgres
DB_PASSWORD=your-postgres-password
DB_HOST=localhost
DB_PORT=5432

# Optional — app works without these using a mock fallback
RAZORPAY_KEY_ID=rzp_test_xxxxxxxxxxxx
RAZORPAY_KEY_SECRET=your-razorpay-secret-here
```

### 5. Set up the database
Create the database in PostgreSQL:
```sql
CREATE DATABASE crm_db;
```

Then run migrations:
```bash
python manage.py migrate
python manage.py createsuperuser
```

### 6. Pull the AI models (one-time)
```bash
ollama pull llama3.2-vision    # reads business card images (~8 GB)
ollama pull llama3.2           # chat assistant (~2 GB)
ollama pull nomic-embed-text   # semantic search (~300 MB)
```

### 7. Start all services

Open 4 separate terminal tabs with the venv activated:

**Tab 1 — Django:**
```bash
python manage.py runserver
```

**Tab 2 — Celery:**
```bash
celery -A card_manager worker --loglevel=info
```

**Tab 3 — Redis** (if not running as a system service):
```bash
redis-server
```

**Tab 4 — Ollama** (if not running as a system service):
```bash
ollama serve
```

Open `http://127.0.0.1:8000` in your browser and log in with the superuser credentials you created above.

## 🧠 Using the AI Assistant

Ensure Ollama is running. The CRM connects to the local API at `http://localhost:11434`. You can verify it is working by running:

```bash
curl http://localhost:11434/api/generate -d '{"model": "llama3.2", "prompt":"test"}'
```

## 📂 Project Structure

* `scanner/` — Main app: models, views, graph services, RAG, tasks
* `scanner/graph_services.py` — Knowledge Graph entity and relationship logic
* `scanner/rag_services.py` — Vector storage and AI context retrieval
* `scanner/tasks.py` — Celery background tasks (card OCR, RAG indexing)
* `scanner/backends.py` — Custom auth backend (login via username, email, or phone)
* `scanner/middleware.py` — Maintenance mode, upload limits, session timeout
* `scanner/templates/scanner/` — All HTML templates
* `.env.example` — Template for required environment variables

## Common Errors

| Error | Fix |
|-------|-----|
| `connection refused` on DB | PostgreSQL not running, or wrong password in `.env` |
| `connection refused` on Redis | Run `redis-server` |
| Card stuck on "AI is scanning" | Celery or Ollama not running |
| `ModuleNotFoundError` | Venv not activated, or `pip install -r requirements.txt` not done |

---

*Developed by Rehansh Shrivastava*
