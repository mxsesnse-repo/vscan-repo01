# AI-Powered Smart CRM & Card Scanner

A complete, end-to-end CRM and networking platform that automates business card ingestion, maps professional relationships using a Knowledge Graph, tracks sales pipelines, and provides an AI-powered assistant using local Large Language Models (LLMs).

## 🚀 Key Features

* **Smart Business Card Scanner:** Automated OCR ingestion of physical business cards using a local vision model (Ollama).
* **Knowledge Graph Engine:** Maps relationships between contacts, companies, events, domains, and sales opportunities to visualize your network.
* **Opportunity Pipeline:** Full-stack pipeline management to track deal stages (Lead, Pitching, Negotiation, Closed Won/Lost).
* **Duplicate Detection:** Automatically flags contacts with matching email or phone on approval.
* **Domain-Based Tagging:** Tag contacts by industry/domain to discover connections across your network.
* **Local AI Assistant:** A privacy-first RAG (Retrieval-Augmented Generation) chat assistant, capable of answering queries based on your private CRM data without sending info to a third-party cloud LLM provider.
* **Admin Dashboard:** Staff-only panel with user management, billing, ad approvals, server health metrics, and live config controls — served from its own styled login page, separate from Django's default admin.
* **Background Processing:** Utilizes Celery and Redis to handle heavy AI/OCR tasks asynchronously without lagging the UI.

## 🛠 Tech Stack

* **Backend:** Django 5.x (Python)
* **Database:** PostgreSQL (Cloud SQL in production)
* **Task Queue:** Redis + Celery
* **AI/LLM:** Ollama — vision model for OCR (`llava-phi3`), chat model (`llama3.2`), embeddings model (`nomic-embed-text`)
* **Frontend:** Bootstrap 5, Vanilla JavaScript
* **Vector Store:** ChromaDB
* **Payments:** Razorpay
* **Hosting:** Google Cloud Run + Cloud SQL + a separate GCE VM running Ollama

## 📦 Prerequisites (local development)

* Python 3.11+
* PostgreSQL
* Redis
* Ollama — download from [ollama.com](https://ollama.com)

## ⚙️ Local Installation

### 1. Clone the repository
```bash
git clone https://github.com/mxsesnse-repo/vscan-repo01.git
cd vscan-repo01
```

### 2. Create a virtual environment
```bash
python -m venv venv
```

**Activate it:**
* **Linux / macOS:** `source venv/bin/activate`
* **Windows:** `venv\Scripts\activate`

### 3. Install dependencies
```bash
pip install -r requirements.txt
```

### 4. Configure environment variables

Copy `.env.example` to `.env`:
```bash
# Linux / macOS
cp .env.example .env

# Windows
copy .env.example .env
```

Then open `.env` and fill in your values:
```env
SECRET_KEY=your-secret-key-here
DB_NAME=crm_db
DB_USER=postgres
DB_PASSWORD=your-postgres-password
DB_HOST=localhost
DB_PORT=5432

# Ollama — defaults to localhost if omitted, only needed if Ollama runs elsewhere
OLLAMA_HOST=http://localhost:11434

# Optional — app works without these using a mock fallback
RAZORPAY_KEY_ID=rzp_test_xxxxxxxxxxxx
RAZORPAY_KEY_SECRET=your-razorpay-secret-here
GOOGLE_CLIENT_ID=your-google-client-id
GOOGLE_API_KEY=your-google-api-key
```

> ⚠️ **Never commit your real `.env` file.** Make sure it's listed in `.gitignore` before your first commit. All real secrets (DB password, Razorpay keys, Django `SECRET_KEY`) should only ever live in your local `.env` or in Secret Manager in production — never hardcoded into `settings.py` or any other tracked file.

### 5. Set up the database

Create the database in PostgreSQL:
```sql
CREATE DATABASE crm_db;
```

Then run migrations and create your admin account:
```bash
python manage.py migrate
python manage.py createsuperuser
```

The account you create here needs `is_staff=True` to access the admin panel — `createsuperuser` sets this automatically.

### 6. Pull the AI models (one-time)
```bash
ollama pull llava-phi3         # reads business card images
ollama pull llama3.2           # chat assistant
ollama pull nomic-embed-text   # semantic search / RAG
```

### 7. Start all services

Open **4 separate terminal tabs** with the virtual environment activated in each:

**Tab 1 — Django:**
```bash
python manage.py runserver
```

**Tab 2 — Celery:**
```bash
celery -A card_manager worker --loglevel=info
```

**Tab 3 — Redis:** *(if not running as a system service)*
```bash
redis-server
```

**Tab 4 — Ollama:** *(if not running as a system service)*
```bash
ollama serve
```

Open `http://127.0.0.1:8000` in your browser and log in with the superuser credentials you created above.

## 🧠 Using the AI Assistant Locally

Ensure Ollama is running. By default the app connects to `http://localhost:11434` (overridable via the `OLLAMA_HOST` env var). Verify it's working:
```bash
curl http://localhost:11434/api/generate -d '{"model": "llama3.2", "prompt":"test"}'
```

## 🔐 Accessing the Admin Portal

The custom admin/backend panel lives at `/custom-admin/` and is gated to users with `is_staff=True`. Visiting it while logged out, or as a non-staff user, redirects to the styled login page at:
```
/admin-login/
```
A correct username/password for a non-staff account will **not** be logged in — it shows "This account does not have backend access." Only staff accounts can authenticate here.

Django's default built-in admin (`/admin/`) has been intentionally removed from this project; `/custom-admin/` is the only backend panel.

## ☁️ Production Deployment (Google Cloud Platform)

This app runs in production as three separate pieces:

| Component | Where it runs | Why |
|---|---|---|
| Django app (Cloud Run) | Serverless container, auto-deployed from this GitHub repo | Scales to zero, no server to manage |
| PostgreSQL | Cloud SQL | Managed, durable database |
| Ollama (vision/chat/embedding models) | A dedicated GCE VM | Cloud Run has no persistent GPU/disk suited to serving local LLMs |

Cloud Run reaches the Ollama VM over a private network using a **Serverless VPC Access connector**, and reaches Cloud SQL via the built-in Cloud SQL connection (Unix socket), not the public internet.

### A. One-time setup — Ollama VM

1. **Compute Engine → Create Instance**
   - Name: `ollama-server`, Region/Zone: same region as your Cloud Run service (e.g. `asia-south1`)
   - Machine type: a GPU-backed type (e.g. `g2-standard-4` with an NVIDIA L4) for usable inference speed, or a plain `e2-standard-4` if running CPU-only
   - Boot disk: Ubuntu 22.04 LTS, 100 GB+ (model weights are large)
2. SSH into the VM and install Ollama:
   ```bash
   curl -fsSL https://ollama.com/install.sh | sh
   ollama pull llava-phi3
   ollama pull llama3.2
   ollama pull nomic-embed-text
   ```
3. Make Ollama listen on the network, not just `localhost`:
   ```bash
   sudo systemctl edit ollama
   ```
   Add:
   ```ini
   [Service]
   Environment="OLLAMA_HOST=0.0.0.0:11434"
   ```
   Then:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl restart ollama
   ```
4. Note the VM's **internal IP** (Compute Engine → VM instances list) — you'll need it below.

### B. One-time setup — Networking

1. **VPC Network → Serverless VPC Access → Create Connector**
   - Name: `ollama-connector`, region matching your Cloud Run service, network `default`, IP range e.g. `10.8.0.0/28`
2. **VPC Network → Firewall → Create Firewall Rule**
   - Name: `allow-ollama-from-vpc-connector`, direction Ingress, targets: all instances (or scope to the VM's tag), source range: the connector's range from above (`10.8.0.0/28`), protocol/port: TCP `11434`

### C. One-time setup — Secrets

**Security → Secret Manager → Create Secret**, one per item:
- `django-secret-key`
- `db-password`
- `razorpay-key-id`
- `razorpay-key-secret`

### D. Cloud Run service configuration

**Cloud Run → your service → Edit & Deploy New Revision:**

**Variables & Secrets tab — Environment variables:**
```
DB_NAME=crm_db
DB_USER=postgres
DB_HOST=/cloudsql/<PROJECT>:<REGION>:<CLOUD_SQL_INSTANCE>
DB_PORT=5432
OLLAMA_HOST=http://<OLLAMA_VM_INTERNAL_IP>:11434
```

**Variables & Secrets tab — Secrets (reference, exposed as env vars):**
```
SECRET_KEY          ← django-secret-key
DB_PASSWORD         ← db-password
RAZORPAY_KEY_ID     ← razorpay-key-id
RAZORPAY_KEY_SECRET ← razorpay-key-secret
```

**Connections tab:**
- Cloud SQL connections → add your instance
- VPC connector → `ollama-connector`, traffic routing set to route only private-IP traffic through the connector (so general internet access is unaffected)

Click **Deploy**.

### E. Ongoing deploys

This repo is connected to Cloud Run for **continuous deployment** — every push to `main` triggers an automatic Cloud Build + redeploy. No manual `gcloud run deploy` is needed for code changes. Check **Cloud Run → Triggers** or **Cloud Build → History** to watch a deploy in progress.

> Environment variables/secrets/connections (Section D) only need to be set once per service, not on every push — they persist across revisions unless you change them.

### F. Verifying a deployment

After a push triggers a new revision, check in this order:
1. Visit the Cloud Run URL — the app should load (confirms the build/boot succeeded).
2. Register a new account — confirms the Cloud SQL connection is working.
3. Upload a business card photo and watch it process — confirms the Ollama VM is reachable over the VPC connector.
4. Visit `/admin-login/`, log in with a staff account — confirms admin access.
5. Visit `/admin/` — should return 404 (default Django admin is removed).

## 📂 Project Structure

* `scanner/` — Main app: models, views, graph services, RAG, tasks
* `scanner/graph_services.py` — Knowledge Graph entity and relationship logic
* `scanner/rag_services.py` — Vector storage and AI context retrieval (Ollama embeddings)
* `scanner/tasks.py` — Celery background tasks (card OCR via Ollama vision model, RAG indexing)
* `scanner/backends.py` — Custom auth backend (login via username, email, or phone)
* `scanner/middleware.py` — Maintenance mode, upload limits, session timeout
* `scanner/templates/scanner/` — All HTML templates, including `admin_login.html` (custom backend login page)
* `.env.example` — Template for required environment variables

## ⚠️ Common Errors

| Error | Fix |
| --- | --- |
| **Server returned an HTML error page on register/login** | Usually a misconfigured or broken `settings.py` — check `DATABASES` env vars are actually set and valid Python |
| **connection refused on DB (local)** | PostgreSQL not running, or wrong password in `.env` |
| **connection refused on DB (Cloud Run)** | Cloud SQL connection not attached to the service, or `DB_HOST` isn't the correct `/cloudsql/...` socket path |
| **connection refused on Redis** | Run `redis-server` |
| **Card stuck on "AI is scanning" (local)** | Celery or Ollama not running |
| **Card stuck on "AI is scanning" (Cloud Run)** | `OLLAMA_HOST` not set, VPC connector missing, or firewall rule blocking port 11434 |
| **ModuleNotFoundError** | Venv not activated, or `pip install -r requirements.txt` not done |
| **Can't reach `/custom-admin/`** | Account isn't marked `is_staff=True` — log in at `/admin-login/`, not `/admin/` |

---

*Developed by Rehansh Shrivastava*