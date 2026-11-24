# Slop Gate (v1 — Pre-Flight Check & Owner Sign-Off)

A local-first web application that prevents creators from sending AI slop to readers by catching cross-page contradictions, chart-vs-claim clashes, weak Ghost-Deck storylines, and missing context—followed by a mandatory **Final Page-by-Page Read-Through** and a subtle **`✓ Reviewed by <Owner Name>`** PDF accountability stamp.

## Quick Start

```bash
# 1. Configure your Gemini API key (optional — runs in Local Demo Mode without one,
#    or paste your key inside the UI's "Model & Key" modal!)
cp .env.example .env

# 2. Start the FastAPI server (serves both API and web UI)
PYTHONPATH=backend .venv/bin/uvicorn app.main:app --reload --port 8000
```

Open **http://localhost:8000** in your browser.

> **Demo Notice:** Only upload documents you would be comfortable pasting into ChatGPT or Gemini. Do not upload confidential enterprise documents.

## Running Tests & 10-PDF Calibration Benchmark

```bash
# Run unit & API integration tests
.venv/bin/pytest backend/tests -v

# Run the 10-PDF Sharp / Slop / Hard calibration benchmark
# (uses Local Demo Mode if GEMINI_API_KEY is unset; uses Live Gemini when set)
.venv/bin/python eval/run_benchmark.py --runs 1

# Benchmark a specific Gemini model across 3 runs for variance checking
GEMINI_API_KEY=your_key .venv/bin/python eval/run_benchmark.py --model gemini-3.1-pro-preview --runs 3
```

## Deploying to Google Cloud Run (Sponsored Beta)

```bash
# 1. Authenticate and pick your GCP project
gcloud auth login
gcloud config set project YOUR_GCP_PROJECT_ID

# 2. Deploy single-container Cloud Run service with sponsored Gemini key + guardrails
GEMINI_API_KEY="AIza..." \
SLOP_BETA_CODE="choose-an-invite-code" \
SLOP_DAILY_RUN_LIMIT_PER_IP=15 \
SLOP_ADMIN_TOKEN="choose-an-admin-secret" \
./deploy_cloudrun.sh
```

- **Spend protection:** `SLOP_BETA_CODE` gates access behind a lightweight invite modal (leave unset for open access), and `SLOP_DAILY_RUN_LIMIT_PER_IP` caps sponsored live runs per 24h per hashed IP (testers can always bypass by entering their own key in `Model & Key`).
- **Durable Feedback & Logging:** Every 1-click rating/comment, funnel transition, token/cost metric, backend exception, and browser JS error is emitted as Google Cloud Logging structured JSON (`stdout`)—persisting permanently in **Cloud Logging (Logs Explorer)** even after Cloud Run scales to zero:
  - Feedback: `resource.type="cloud_run_revision" jsonPayload.event="user_feedback"`
  - Errors (backend + frontend): `resource.type="cloud_run_revision" severity>=ERROR`
  - Funnel & behavior: `resource.type="cloud_run_revision" jsonPayload.event!=""`
  - Live summary JSON (while warm): `curl -H "X-Admin-Token: $SLOP_ADMIN_TOKEN" https://<service-url>/api/admin/telemetry`
