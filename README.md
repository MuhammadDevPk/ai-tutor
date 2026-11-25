# AI Tutor

An AI tutor that teaches like a real teacher: it engages the student, teaches step by step with a synchronized math whiteboard and a 3D teacher avatar, asks questions to check understanding, and resumes exactly where it left off when interrupted.

Built to run at $0 on free tiers: Next.js + FastAPI + Supabase (pgvector, ltree) + LiveKit + Kokoro TTS, with a Groq/Gemini model waterfall.

- Full plan: [IMPLEMENTATION-PLAN.md](IMPLEMENTATION-PLAN.md)
- Agent harness: [.agents/ARCHITECTURE.md](.agents/ARCHITECTURE.md), [.agents/PATTERNS.md](.agents/PATTERNS.md), [.agents/ROADMAP.md](.agents/ROADMAP.md), [.agents/DECISIONS.md](.agents/DECISIONS.md)

## Status

Phases 1–9 are complete and merged to `main`. Phase 10 is currently in progress on branch `phase-10-hardening`.

- **Phase 1 (Complete):** Monorepo scaffold, PostgreSQL schema with `pgvector` and `ltree` extensions, typed Pydantic v2 schemas with automated OpenAPI client generation, and JWT authentication.
- **Phase 2 (Complete):** Math-aware PDF ingestion (PyMuPDF4LLM), Gemini Vision fallback for complex equations, Syllabus Inspector UI, formula-preserving chunking, and local fastembed vector embeddings.
- **Phase 3 (Complete):** Model-bucket LLM router (Groq multi-model waterfall, Gemini Flash tier-2 failover, Ollama fallback), response header quota governor, circuit breaker, and newline-delimited streaming parser.
- **Phase 4 (Complete):** Explicit 5-state Pedagogical FSM (`ONBOARDING`, `TEACH_STEP`, `MICRO_CHECK`, `INTERRUPT_QA`, `RECAP`), 4,000-token prompt budget assembler, chapter scope guardrails, and CLI text simulation harness.
- **Phase 5 (Complete):** LiveKit WebRTC voice transport, server-side Kokoro-82M TTS streamer (24kHz PCM), Silero VAD, two-stage barge-in controller, and Whisper STT with hallucination guard.
- **Phase 6 (Complete):** Excalidraw native-SVG whiteboard workspace, backend 4-zone spatial layout allocator (1280×720), client MathJax 3 / function-plot SVG compilation, and Circle-to-Ask visual equation matcher.
- **Phase 7 (Complete):** Sample-accurate playout clock sync (±150ms) via server PCM sample counting, unconditional silent Web Audio tap, barge-in rollback, and toggleable dev telemetry HUD.
- **Phase 8 (Complete):** TalkingHead 3D avatar (30fps render loop), HeadAudio AudioWorklet lip-sync integration, and GPU FLIP Full-to-PiP layout transitions.
- **Phase 9 (Complete):** Turn-boundary snapshot persistence to PostgreSQL JSONB, reload recovery on browser refresh, interactive timeline replayer with LaTeX copy, one-click formula cheat-sheet exports, and course mastery dashboard.
- **Phase 10 (In progress):** 45-minute continuous soak testing, Groq 429 chaos failover validation, Supabase keep-alive safeguards, and $0 deployment manifests.

## Run It Locally

### Prerequisites

- **Node.js 20+** and **pnpm** (v10+ or Corepack-managed pnpm 12)
- **Python 3.12+** and **uv**
- **PostgreSQL 16** with `pgvector` and `ltree` extensions available

### 1. Clone the repository

```bash
git clone <repo-url>
cd ai-tutor
```

### 2. Set up the database

Create a PostgreSQL database (e.g. `ai_tutor`) and enable the required extensions:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS ltree;
```

### 3. Configure API environment variables

Copy `apps/api/.env.example` to `apps/api/.env`:

```bash
cp apps/api/.env.example apps/api/.env
```

Open `apps/api/.env` and fill in the values:
- `DATABASE_URL`: Connection string pointing to your local PostgreSQL database (e.g. `postgresql://postgres:postgres@localhost:5432/ai_tutor`).
- `JWT_SECRET`: Any long random secret string.
- `GROQ_API_KEY` and `GEMINI_API_KEY`: API keys for the LLM waterfall.
- `LIVEKIT_URL`, `LIVEKIT_API_KEY`, and `LIVEKIT_API_SECRET`: Credentials for LiveKit voice transport.

> **Important:** Never commit the `.env` file to version control.
> Without LiveKit keys, the classroom UI loads, but live voice will be unavailable.
> Without Groq or Gemini keys, the tutor will not be able to answer questions.

### 4. Install dependencies

Install frontend dependencies from the repository root:

```bash
pnpm install
```

Install backend dependencies in `apps/api`:

```bash
cd apps/api
uv sync
cd ../..
```

### 5. Run database migrations

Apply all database migrations from `apps/api`:

```bash
cd apps/api
uv run alembic upgrade head
cd ../..
```

### 6. Start the API server

From `apps/api`, start FastAPI with Uvicorn:

```bash
cd apps/api
uv run --with uvicorn python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

*(Note: `uvicorn` is not yet declared as a project dependency in `pyproject.toml` (issue #26), so it is supplied with `--with uvicorn`.)*

The API will be available at `http://127.0.0.1:8000` (interactive API documentation at `http://127.0.0.1:8000/docs`).

### 7. Start the web app

From `apps/web`, start the Next.js development server:

```bash
cd apps/web
pnpm dev
```

*(Alternatively, run `pnpm build && pnpm start` for a production build).*

The web application serves on `http://localhost:3000`.

### 8. Sign in for local development

The API seeds a default development account (`dev@example.com` / `devpassword123`, configured via `DEV_USER_*` values in `.env`). Because the web application does not have a login page yet, obtain an access token by sending a POST request to the API login endpoint:

```bash
curl -X POST http://127.0.0.1:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "dev@example.com", "password": "devpassword123"}'
```

This returns a JSON response containing your token:

```json
{"access_token":"<JWT_TOKEN>","token_type":"bearer"}
```

To authenticate the web client:
1. Open `http://localhost:3000` in your browser.
2. Open Developer Tools (Press `F12` or `Cmd+Option+I` on macOS) and switch to the **Console** tab.
3. Set the `auth_token` key in `localStorage`:
   ```javascript
   localStorage.setItem("auth_token", "<JWT_TOKEN>");
   ```
4. Reload the page.

### 3D Teacher Model

The 3D teacher model asset is located at `apps/web/public/models/avatar.glb` in the repository.

## Verify

Run the full verification gate before submitting changes:

```bash
chmod +x scripts/verify.sh  # Run once after a fresh clone
./scripts/verify.sh --full
```

The `--full` gate runs:
- Architectural guardrails (enforces Do-Not-Build banned patterns)
- Python linting (`ruff`)
- Python type checking (`mypy`)
- Python test suite (`pytest`)
- Web type checking (`tsc --noEmit`)
- Web linting (`eslint`)
- Web production build (`next build`)
- Web secrets-in-bundle check
- Leftover exploratory `spikes/` check
- OpenAPI contract drift check (`pnpm run sync:contracts`)

For fast iterative checks during development, run:

```bash
./scripts/verify.sh --fast
```
