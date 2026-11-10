# ClaimGuard

**Autonomous Multi-Agent Healthcare Insurance Claim Prevention System**
*Prevent the rejection before the claim is submitted.*

ClaimGuard inspects healthcare claims before submission. Eight specialist agents and an orchestrator investigate each claim, a deterministic Python engine decides readiness, Claude writes the explainable assessment, OpenAI independently challenges it, and a person approves every correction.

> **Scope.** Administrative decision support on **synthetic data only**. Not a replacement for clinicians, certified coders, insurers or adjudication systems. `READY` means every configured deterministic check passes. It is not a guarantee of payer approval.

---

## Quick start (local, about 2 minutes)

Requirements: Python 3.11+, Node 18+.

```bash
# 1. backend
cd backend
pip install -r requirements.txt
cp ../.env.example ../.env          # optional: add API keys (see below)
python -m pytest -q                 # 23 tests
uvicorn app.main:app --port 8000    # seeds 100 synthetic claims on first start

# 2. frontend (second terminal)
cd frontend
npm install
npm run dev                         # http://localhost:5173  (proxies /api and /ws to :8000)
```

**Single-process alternative:** `cd frontend && npm run build`, then start the backend. FastAPI serves the built UI at http://localhost:8000.

Open the **Command Centre** and press **Start operation**.

## AI providers

With no keys set, everything runs in **deterministic mode**. The UI says so plainly, and agents record "tools only" rather than pretending to reason.

| Variable | Purpose |
|---|---|
| `ANTHROPIC_API_KEY` | Enables Claude for specialist reasoning and the orchestrator synthesis |
| `CLAUDE_MODEL_ORCHESTRATOR`, `CLAUDE_MODEL_SPECIALIST` | Default `claude-fable-5-2`. Use a cheaper/faster model for specialists if latency matters |
| `OPENAI_API_KEY`, `OPENAI_MODEL` | Enables the independent reviewer. **`OPENAI_MODEL` has no default, so set it** |
| `AI_DEPTH` | `none` · `synthesis` (default: the Documentation Agent reads notes, plus synthesis and review for flagged claims) · `full` (every agent calls Claude) |
| `CLAIM_CONCURRENCY` | Claims processed in parallel (default 6) |

Keys are read only by the backend. The frontend never sees them.

**Before the competition:** the provider calls were built and tested against stubbed HTTP responses only. No live API was reachable while building. With real keys, run a single claim first (`Claims → CLM-0014 → Request reassessment`, AI depth *Synthesis*) and confirm Claude and OpenAI both show `ok` in the AI assessment panel.

## What's measured (seed 42, deterministic mode)

| | Baseline scrubber | ClaimGuard |
|---|---|---|
| Labelled issues detected | 20 / 69 | 66 / 69 |
| False-positive claims | 0 | 0 |
| Claims with a known issue passed through | 44 | 3 |
| Validated correction proposals | 0 | 28 |
| READY before → after approving every validated correction | — | 39 → 64 |
| Conflicts between agents detected / resolved | — | 11 / 11 |

The 3 misses are issues that exist only in free-text clinical notes, which only the Documentation Agent's Claude reading can catch. The baseline runs 6 claim-level rules without cross-record lookups. All of this is synthetic, and the rules were written against the same issue taxonomy as the generator, so treat recall as an upper bound. See `docs/DATA_ASSUMPTIONS.md`. Reference outputs are in `demo/expected_results/`.

## Repository

```
backend/app/
  agents/        base agent, 7 specialists, recovery agent, orchestrator
  ai/            Claude + OpenAI REST clients (failure-contained), prompts
  validation/    deterministic rule engine (18 rules), reference-data loader
  services/      claim versioning, correction workflow, event bus + recorder
  simulation/    seeded dataset generator, benchmark, export
  api/routes.py  REST API      main.py  app, WebSocket /ws/claimguard
backend/tests/   23 tests (the 20 required scenarios + API + agent crash)
frontend/src/    React + TS + Vite + Tailwind + Recharts; 7 screens
data/            exported synthetic dataset and reference rules (seed 42)
demo/            scenarios and expected benchmark results
docs/            ARCHITECTURE, BUILD_LOG, TEST_REPORT, DEMO_SCRIPT, DATA_ASSUMPTIONS
```

## Deployment

- **Backend → Render:** `render.yaml` (Docker). Set the env vars in the Render dashboard. SQLite is per instance and reseeds on an empty disk.
- **Frontend → Vercel:** root `frontend/`, build `npm run build`, output `dist`, env `VITE_API_URL=https://<your-render-app>`. Set `CORS_ORIGINS` on the backend to the Vercel URL.
- **Docker:** `docker build -t claimguard . && docker run -p 8000:8000 --env-file .env claimguard` (builds the UI and serves both).

The local demo needs none of this.
