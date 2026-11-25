# DEPLOYMENT.md — $0 Academic Production Deployment Guide

This guide details the verified zero-cost ($0/month) deployment topology for the **AI Video Tutor** monorepo, covering every component, the one-line Supabase database swap, and complete environment variable documentation by name.

---

## 1. Zero-Cost Topology Overview

The AI Video Tutor is architected for strict $0 perpetual academic operation on free-tier infrastructure without compromising reliability, security, or latency:

```
[Student Browser]
       │
       ├─ HTTPS (UI / Excalidraw / 3D Avatar) ──────> Vercel Hobby Free Tier ($0)
       │                                              (apps/web: Next.js 16 App Router)
       │
       ├─ WebRTC (24kHz Mono PCM Audio + Data) ─────> LiveKit Cloud Build Free ($0)
       │                                              (5,000 participant min/mo, 1,000 agent min/mo)
       │
       └─ REST API / JWT Auth ──────────────────────> Oracle Cloud Always Free ($0) / HF Spaces ($0)
                                                      (apps/api: FastAPI + Alembic + Kokoro ONNX)
                                                               │
                       ┌───────────────────────────────────────┴───────────────────────────────────────┐
                       ▼                                                                               ▼
         Supabase Free Tier ($0)                                                       Cloud & Local AI Providers ($0)
   (PostgreSQL 16 + pgvector + ltree)                                          - Groq Cloud: GPT-OSS 20B/120B, Qwen 27B
   (500MB storage, pooled/direct connections)                                  - Google AI Studio: Gemini 3.8 Flash
                                                                               - Kokoro ONNX int8 (Local CPU TTS)
                                                                               - Silero VAD (Local CPU)
                                                                               - Local Ollama (Offline fallback)
```

| Tier | Component | Free Tier Provider | Cost | Limits / Safeguards |
|---|---|---|---|---|
| **Frontend** | Next.js 16 (App Router) | **Vercel Hobby** | $0/mo | 100GB bandwidth, automatic SSL, edge CDN |
| **Backend API** | FastAPI + Kokoro TTS | **Oracle Cloud Always Free** / **Hugging Face Spaces** / Localhost | $0/mo | Oracle: 4 Ampere A1 ARM cores, 24GB RAM ($0 forever); HF Spaces: Basic CPU |
| **Database** | PostgreSQL 16 + Vector + LTree | **Supabase Free Tier** | $0/mo | 500MB storage, 2 pooled connections; kept active via weekly keep-alive GitHub Action |
| **Realtime Media** | Full-duplex WebRTC | **LiveKit Cloud Build Free** / Local LiveKit binary | $0/mo | 5,000 participant mins + 1,000 agent mins/mo |
| **Inference (Tier 1)** | Streaming LLM + STT | **Groq Cloud (1 Free API Key)** | $0/mo | 3 model buckets (20B, 120B, 27B) + Whisper-large-v3-turbo |
| **Inference (Tier 2)** | Failover LLM + Vision | **Google AI Studio (Free Tier)** | $0/mo | Gemini 3.8 Flash + Gemini 3.5 Flash Lite (no credit card required) |
| **Inference (Tier 3)** | Offline Emergency Fallback | **Local Ollama (`qwen3.8-27b`)** | $0/mo | Runs offline on CPU if all cloud tiers fail |

---

## 2. One-Line Supabase Database Swap

The repository uses PostgreSQL with `vector` (384d) and `ltree` extensions.

### Local Development (Default):
```env
DATABASE_URL=postgresql://postgres:localdev@localhost:5432/ai_tutor
```

### Production Supabase Free Tier Swap:
1. Create a free project at [supabase.com](https://supabase.com).
2. Go to **Project Settings** -> **Database** -> **Connection string** -> **URI** (Transaction Pooler, port 6543):
```env
DATABASE_URL=postgresql://postgres.[YOUR-PROJECT-REF]:[YOUR-PASSWORD]@aws-0-[REGION].pooler.supabase.com:6543/postgres?sslmode=require
```
3. Run Alembic migrations against Supabase:
```bash
cd apps/api
DATABASE_URL="postgresql://postgres.[YOUR-PROJECT-REF]:[YOUR-PASSWORD]@aws-0-[REGION].pooler.supabase.com:6543/postgres?sslmode=require" uv run alembic upgrade head
```
Migration 001 enables `CREATE EXTENSION IF NOT EXISTS vector;` and `CREATE EXTENSION IF NOT EXISTS ltree;` automatically. No manual table creation is required.

---

## 3. Complete Environment Variable Reference

### Backend (`apps/api` / Docker Container)

Set these platform environment variables in your deployment host (Oracle VM, HF Space, or `.env`):

| Variable Name | Required | Default / Format | Description |
|---|---|---|---|
| `DATABASE_URL` | Yes | `postgresql://...` | Connection URI to Supabase PostgreSQL or local Postgres |
| `JWT_SECRET` | Yes | Secure random string (32+ chars) | HMAC-SHA256 secret key for signing auth tokens |
| `JWT_ALGORITHM` | No | `HS256` | JWT signing algorithm |
| `DEV_USER_EMAIL` | No | `dev@example.com` | Email for dev access |
| `DEV_USER_PASSWORD`| No | Secure password | Password for seeded dev account |
| `DEV_USER_ID` | No | `00000000-0000-0000-0000-000000000001` | Dev UUID |
| `GROQ_API_KEY` | Yes | `gsk_...` | Groq Cloud free API key for model buckets & Whisper STT |
| `GROQ_BASE_URL` | No | `https://api.groq.com/openai/v1` | Groq API endpoint |
| `GEMINI_API_KEY` | Yes | `AIzaSy...` | Google AI Studio free key for Vision & Tier-2 failover |
| `GEMINI_MODEL` | No | `gemini-3.8-flash` | Gemini model identifier |
| `LIVEKIT_URL` | Yes | `wss://[project].livekit.cloud` | LiveKit server WebRTC signaling URL |
| `LIVEKIT_API_KEY` | Yes | `API...` | LiveKit API Key for room & token minting |
| `LIVEKIT_API_SECRET`| Yes | Secure secret | LiveKit API Secret for signing room JWTs |
| `OLLAMA_BASE_URL` | No | `http://localhost:11434` | Local Ollama base URL for offline Tier-3 failover |
| `LLM_REQUEST_TIMEOUT_S` | No | `60.0` | Per-request provider timeout in seconds |
| `PORT` | No | `8000` | Port for FastAPI uvicorn server |
| `RUN_MODE` | No | `api` | `api` (FastAPI), `worker` (LiveKit agent), or `both` |

> [!CAUTION]
> NEVER commit actual secret values to git or `.env` tracked files. All secrets must be provided via platform environment settings.

---

### Frontend (`apps/web` / Vercel)

Set these environment variables in the Vercel Project Settings:

| Variable Name | Required | Description |
|---|---|---|
| `NEXT_PUBLIC_API_URL` | Yes | Public HTTPS URL of the deployed FastAPI backend (e.g. `https://api.yourdomain.com`) |
| `NEXT_PUBLIC_LIVEKIT_URL` | Yes | Public WSS URL of LiveKit server (e.g. `wss://[project].livekit.cloud`) |
| `NEXT_PUBLIC_AVATAR_MODEL_URL` | No | Path to 3D avatar GLB model (defaults to `/models/avatar.glb`) |

> [!NOTE]
> Next.js bundles strictly variables prefixed with `NEXT_PUBLIC_`. All backend keys (`GROQ_API_KEY`, `LIVEKIT_API_SECRET`, `DATABASE_URL`) are server-only and mechanically verified to never leak into client bundles via `scripts/check-bundle-secrets.sh`.

---

### GitHub Actions Secrets (Automation & Safeguards)

Configure under **Repository Settings** -> **Secrets and variables** -> **Actions**:

| Secret Name | Required for | Description |
|---|---|---|
| `SUPABASE_DATABASE_URL` | Keep-alive & Weekly Backup workflows | Supabase pooled connection URL to prevent free-tier 7-day pause and run weekly backups |

---

## 4. Step-by-Step Deployment Walkthrough

### Step A: Deploy Database (Supabase)
1. Create Supabase project.
2. Note connection string with pooler (`aws-0-[region].pooler.supabase.com:6543`).
3. Run Alembic upgrade: `uv run alembic upgrade head`.

### Step B: Deploy Backend (Oracle Always Free / Docker)
1. Build the container image using `apps/api/Dockerfile`:
```bash
docker build -t ai-tutor-api:latest -f apps/api/Dockerfile apps/api
```
2. Run the API server:
```bash
docker run -d \
  -p 8000:8000 \
  -e DATABASE_URL="postgresql://postgres.[ref]:[pw]@...supabase.com:6543/postgres?sslmode=require" \
  -e JWT_SECRET="your-32-char-random-secret" \
  -e GROQ_API_KEY="gsk_..." \
  -e GEMINI_API_KEY="AIzaSy..." \
  -e LIVEKIT_URL="wss://[ref].livekit.cloud" \
  -e LIVEKIT_API_KEY="..." \
  -e LIVEKIT_API_SECRET="..." \
  -e RUN_MODE="both" \
  ai-tutor-api:latest
```

### Step C: Deploy Frontend (Vercel)
1. Import repository to Vercel.
2. Select root directory or `apps/web`.
3. Set Framework to **Next.js**.
4. Configure environment variables:
   - `NEXT_PUBLIC_API_URL`
   - `NEXT_PUBLIC_LIVEKIT_URL`
5. Click **Deploy**. Vercel will build using Next.js 16 and cache production assets.

---

## 5. Free-Tier Safeguards & Maintenance

1. **Supabase Auto-Pause Protection:** Supabase free-tier projects pause after 7 consecutive days of inactivity. The scheduled GitHub Action `.github/workflows/keep-alive.yml` pings the database weekly to ensure zero downtime.
2. **Weekly Disaster Backup:** `.github/workflows/weekly-backup.yml` exports courses, syllabus nodes, and session events as logical JSON artifacts stored in GitHub Actions run history.
3. **Secrets Leak Gate:** `scripts/check-bundle-secrets.sh` runs during full verification and CI builds to prevent any accidental leakage of server tokens into browser JavaScript.
