# Build Log

Build started 2026-11-10 (Asia/Dubai). Single developer plus Claude. The eight-day plan was compressed into one build session. Day 6–8 items (deployment, rehearsal, polish) remain for you.

## Environment assessment
Empty workspace, no existing repository. Python 3.13, Node 22, 2 CPUs, outbound access limited to package registries (no Anthropic/OpenAI API access, no shadcn registry, no Google Fonts). Consequences: provider calls are tested with stubbed HTTP; shadcn-style components are hand-written; fonts fall back to the system font when offline.

## Milestones

### M1 · Foundation (plan Day 1) — done
- **Implemented:** SQLAlchemy models (22 tables), seeded generator with ground-truth labels, 18-rule deterministic engine, readiness score, baseline scrubber.
- **Tested:** generator determinism; every claim's failing rules equal its labelled deterministic rules (0 mismatches on 100 claims).
- **Changed:** the readiness score originally gave blocked claims ~90+. A critical failure now zeroes its dimension.

### M2–M3 · AI infrastructure and specialist agents (Days 2–4) — done
- **Implemented:** Claude/OpenAI REST clients with JSON extraction, Pydantic validation, timeouts and contained failures; agent base class with logged tools; 7 specialists; Recovery Agent; orchestrator with parallel dispatch, review requests, conflict detection, bounded reassessment, compliance gate, synthesis, independent review; Recorder plus EventBus.
- **Failed, then fixed:** `engine_status` included AI escalations, so "rules alone" was wrong in the audit. It now uses `determine_outcome(results)` only.
- **Failed, then fixed:** the Compliance final gate was recorded as a reassessment iteration (the Control Room showed "reassessed 106"). It is now a separate first-iteration run.

### M4 · Critical milestone (end of Day 5) — **met**
ClaimGuard analyses a claim, coordinates agents, identifies issues, generates proposals, and passes them through deterministic validation. Full 100-claim run in ~3 s deterministic; 232 stubbed AI calls with 0 failures at depth `synthesis`.

### M5 · API, WebSocket, corrections, benchmark — done
REST endpoints as specified plus health, demo load, global corrections and rules. Role-aware approve/edit/reject with versioning. Reproducible benchmark saved to the database and to JSON.

### M6 · Frontend (Day 6) — done
Seven screens: Command Centre, Claims, Claim Intelligence, Agent Control Room, Correction Workspace, Analytics, Audit. Checked by driving headless Chrome: start the operation, live statuses mid-run, approve a correction, audit entry.
- **Fixed after screenshots:** clipped and skipped chart labels; an approved card vanished on refresh before the operator saw the before/after; empty original values rendered blank; the approved badge kept its pending colour.
- Chart palette run through the colour-vision validator (baseline indigo vs ClaimGuard teal: pass).

### M7 · Integration (Day 7) — mostly done
Full workflow tested end to end; provider-failure scenarios tested. **Not done:** live provider calls.

### M8 · Competition prep (Day 8) — **remaining**
Deploy, add real keys and verify one claim, time an AI run, rehearse, record backup.

## Schedule
On schedule for the core product. The open risk is the live-provider check, and it is the first thing to do.

## Next steps (in order)
1. Add keys; run CLM-0014 at *Synthesis*; confirm both providers show `ok`.
2. Time a 100-claim *Synthesis* run; choose Plan A or B in `DEMO_SCRIPT.md`.
3. Deploy (Render + Vercel) or demo locally.
4. Rehearse twice; record backup.
