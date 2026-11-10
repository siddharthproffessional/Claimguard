# Test Report

Run: `cd backend && python -m pytest -q` → **23 passed** (about 10 s). In-memory SQLite, providers disabled unless a test stubs the HTTP layer (`providers._post`), so the real request building, JSON parsing and schema validation code runs.

| # | Required scenario | Test | Result |
|---|---|---|---|
| 1 | Valid claim | READY, score 100, no proposals, disclaimer present | Pass |
| 2 | Missing patient information | ELIG-001 → registry-backed proposal with evidence | Pass |
| 3 | Invalid policy dates | Effective after termination → ELIG-003 human review; lapsed coverage → HUMAN_REVIEW | Pass |
| 4 | Missing documentation | Repository doc → attach proposal; absent doc → external action, **no invented proposal** | Pass |
| 5 | Invalid synthetic code | COD-001/002 fail; proposals need certified coder and say they are not a coding determination | Pass |
| 6 | Coding mismatch | COD-003 → human review, no proposal | Pass |
| 7 | Missing authorization | On file → link proposal; never obtained → no proposal | Pass |
| 8 | Expired authorization | AUTH-002 "not valid on the date of service", external action | Pass |
| 9 | Duplicate claim | Later copy flagged, original clean, no "fraud" wording, Fraud→Compliance message | Pass |
| 10 | Conflicting agent findings | Authorization vs Eligibility detected, iteration 2 revises, resolved, not READY, audited | Pass |
| 11 | OpenAI review failure | Claude ok, OpenAI timeout → status unchanged, `ai_provider_failure` audited, reviewer run shown **failed** | Pass |
| 12 | Claude API failure | Connection error → no agent marked failed, no fake `ai_used`, deterministic correction still produced | Pass |
| 13 | Invalid correction proposal | Wrong type → 422; non-editable field → refused; version unchanged; 2 `correction_invalid` audits; billing operator on a coder proposal → 403 | Pass |
| 14 | Correction approval | REQUIRES_CORRECTION → READY, v2 written, **v1 unchanged**, approval row, re-approve → 409 | Pass |
| 15 | Correction rejection | Claim unchanged, proposal rejected, audited | Pass |
| 16 | Human review escalation | Rules pass, Claude reads the note and raises a concern → HUMAN_REVIEW; Claude saying READY on a failing claim → stays failing, disagreement logged | Pass |
| 17 | Reassessment after correction | Attach document → reassess → READY on v2, no new proposals | Pass |
| 18 | Reproducible benchmark | Two runs, same seed → identical results (timings excluded); saved runs; ClaimGuard > baseline, 0 false positives | Pass |
| 19 | Audit log creation | Analysis, proposal, assessment, approval and validation events; human actor; before/after; evidence; >10 tool calls | Pass |
| 20 | Readiness calculation | Weighted dimensions; critical failure zeroes its dimension; blocking failure never READY; escalation → HUMAN_REVIEW | Pass |
| + | API end to end | Health, list, analyse, validation, viewer 403, approve 200, 404s, 422, all GET endpoints, WebSocket hello | Pass |
| + | API create claim | POST /claims → analyse → detected as a duplicate of its source | Pass |
| + | Agent crash | Coding agent raises → run failed, claim escalated, pipeline completes | Pass |

## Additional verification (not in pytest)
- **Full deterministic simulation (seed 42):** baseline 20/69 detected, ClaimGuard 66/69, 0 false-positive claims, 11/11 conflicts resolved, 28 validated proposals; READY 39 → 64 with the simulated operator.
- **Full simulation with stubbed AI (depth `synthesis`):** 232 provider calls, 0 failures, 69/69 detected. 3 false positives came from the stub's crude keyword matching ("left knee" in diagnoses), not from a model; this shows the benchmark does count AI-raised false positives.
- **Browser (headless Chrome against the built UI):** all 7 screens render with no JS errors; Start operation shows live statuses and claim IDs mid-run; approving CLM-0009 shows v2 Requires correction 95 → Ready 100; Audit → Human decisions shows the entry.

## Not tested
- **Live Anthropic and OpenAI APIs** (unreachable from the build environment). Model IDs and request formats follow the public Messages and Chat Completions APIs. Verify with real keys before the demo.
- Deployment to Render or Vercel.
- Multi-user concurrency.
