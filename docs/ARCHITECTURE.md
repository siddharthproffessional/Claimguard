# ClaimGuard Architecture

## 1. Shape

A **modular monolith**: one FastAPI process, SQLite, a WebSocket event stream, and a React SPA.

```
React SPA ──REST──▶ FastAPI routes ──▶ Orchestrator ──▶ 7 specialist agents ──▶ tools ──▶ RefData / Validation engine
    ▲                    │                 │                 (parallel, asyncio)
    └──── WebSocket ◀─ EventBus ◀── Recorder (persists every task, message, run, tool call, audit event, then publishes)
                                           │
                                           ├─▶ Recovery Agent ─▶ proposals ─▶ dry-run validation
                                           ├─▶ Compliance readiness gate
                                           ├─▶ Claude synthesis   (advisory)
                                           └─▶ OpenAI review      (advisory, adversarial)
```

**Core principle.** Business logic and LLM reasoning are separate. `app/validation/engine.py` is pure Python with no model input, and it alone decides READY / REQUIRES_CORRECTION. Model output can **only add** escalations to HUMAN_REVIEW. It can never clear a failed rule or promote a claim.

## 2. Orchestration flow (per claim) — `app/agents/orchestrator.py`

1. Snapshot the current claim version into a `ClaimContext`, which holds a versioned `SharedState`.
2. **Intake** runs first: parse, mandatory fields, classify, route.
3. **Six specialists run in parallel**: eligibility, documentation, coding, authorization, fraud/duplicate, compliance. Each gets a persisted `AgentTask` and a task-assignment message.
4. Agents return structured `AgentOutput` (Pydantic): findings with evidence, uncertainty, and `review_requests` addressed to peers.
5. **Conflict detection** (`detect_conflicts`) looks for incompatible positions:
   - authorization says *valid*, eligibility says *coverage inactive*
   - authorization says *valid*, compliance says *plan excludes procedure*
   - coding says *codes consistent*, documentation says *document names a different procedure*
   - an agent's AI reasoning raises a concern no deterministic rule supports
6. **Reassessment loop** (max `MAX_AGENT_ITERATIONS`, default 3): review requests and open conflicts are relayed as agent-to-agent messages, and the target agents re-run with the peer's evidence. If a target revises its position, the conflict is marked *resolved*. Anything still open at the limit is *escalated* to human review. AI-vs-rules conflicts always escalate.
7. **Validation engine** runs all 18 rules (logged as a tool call) and persists the results.
8. **Recovery Agent** consolidates and prioritises failures, drafts correction proposals from deterministic evidence only, dry-runs each one, and projects the status if every proposal were approved.
9. **Compliance readiness gate** blocks READY while any rule fails or any escalation exists. It also flags proposals without evidence.
10. **Claude synthesis** (when AI is enabled and the claim is flagged, or always at depth `full`): summary, risks, conflict adjudication, recommended status. A different recommendation is logged as a `model_disagreement`. If the engine says READY and Claude does not, the claim escalates.
11. **OpenAI independent review**: instructed to test the assessment, not agree with it. Disagreements are preserved in the audit log. If the assessment is READY and the reviewer challenges it, the claim escalates (`REVIEWER_CAN_ESCALATE`).
12. The final assessment is stored on the claim. Agent statuses return to idle and events are published.

**Failure handling.** Every provider call returns a result object and never raises. An agent exception marks that run `failed`, and the claim escalates to human review instead of being marked READY. Each agent's AI step has its own timeout (`AGENT_TIMEOUT_S`) and provider calls have `AI_TIMEOUT_S`. A failed review is recorded as *failed* and never shown as completed.

### AI depth

| Depth | Claude calls | OpenAI calls | ~Calls / 100 claims |
|---|---|---|---|
| `none` | 0 | 0 | 0 |
| `synthesis` (default) | Documentation Agent on every claim with documents, plus synthesis for flagged claims | review for flagged claims | ~230 |
| `full` | every specialist on every claim, plus synthesis for every claim | review for every claim | ~1,000 |

The Documentation Agent uses Claude by default because free-text notes are the one thing rules cannot read.

## 3. Agent responsibility matrix

| Agent | Responsibility | Tools (all logged) | Rules owned | Talks to |
|---|---|---|---|---|
| Orchestrator | Assign, relay, detect conflicts, iterate, validate, synthesise | `validation_engine.validate_claim` | — | all |
| Intake | Parse, mandatory fields, classify, route | `parse_claim`, `classify_claim`, `run_validation_rules` | COMP-001, COMP-002 | orchestrator |
| Eligibility | Patient and policy registry, coverage dates | `lookup_patient`, `lookup_policy` | ELIG-001…004 | → Authorization (coverage inactive) |
| Documentation | Required documents, repository search, document–claim consistency, free-text reading (AI) | `get_required_documents`, `list_attached_documents`, `search_document_repository`, `extract_documented_codes` | DOC-001, DOC-002 | → Coding (mismatch); replies to Coding |
| Medical Coding | Codes vs the **synthetic** reference, compatibility table | `lookup_code_reference` | COD-001…003 | → Documentation (invalid code) |
| Prior Authorization | Payer auth requirements, auth records | `get_authorization_requirements`, `lookup_authorization`, `search_authorizations_on_file` | AUTH-001, AUTH-002 | revises on Eligibility / Compliance evidence |
| Fraud & Duplicate | Control number and billing-combination duplicates, arithmetic, unit limits. Never says "fraud" | `find_matching_claims` | DUP-001, DUP-002, BILL-001, BILL-002 | → Compliance (hold) |
| Compliance | Payer rules, plan exclusions, final readiness gate, unsupported recommendations | `load_payer_rules`, `audit_correction_proposals`, `readiness_gate` | COV-001, COMP-001 | → Authorization (exclusion) |
| Recovery | Consolidate, prioritise, draft proposals, dry-run, effort estimate | `consolidate_findings`, `draft_correction_proposals`, `dry_run_validation`, `estimate_effort` | — | orchestrator |
| Independent reviewer | Challenge the assessment | `openai.chat.completions` | — | orchestrator |

## 4. Validation, outcomes and readiness

Each rule result carries a rule ID, claim ID, status, severity, explanation, evidence, next action, and a `resolution`: *correctable* (a fix exists on file), *external_action* (staff must obtain something), or *human_review* (needs judgment).

- **HUMAN_REVIEW** if any failure needs human review, or any escalation exists
- **REQUIRES_CORRECTION** if failures remain and all are correctable or external
- **READY** only if no rule fails and no escalation exists

**Readiness score (0–100):** a weighted mean of six dimension scores (eligibility 20, documentation 20, coding 20, authorization 15, billing 15, compliance 10; configurable through `SCORING_WEIGHTS`). A dimension score is the share of its applicable rules that pass (a warning counts half). **A critical failure sets its dimension to 0.** The score is an internal indicator, and status never depends on it.

## 5. Correction workflow — `app/services/corrections.py`

- Proposals are drafted only from deterministic evidence: registry values, unattached repository documents, authorizations on file, recalculated arithmetic, and codes from the structured document extract. Each one names its agent, rule, evidence and uncertainty.
- Allowed edits: administrative fields only (policy number, member ID, DOB, place of service, authorization number, totals, line codes, units, amounts, attaching an existing document of the same patient). Clinical documents are never edited.
- **Role-aware:** code changes need `certified_coder` or `supervisor`. A `viewer` can decide nothing. The role comes from the `X-Role` header, which is demo identity, not authentication.
- **Approve:** the patch is re-checked against the allow-list, dry-run validated (refused if it introduces any new failure), written as a new immutable `ClaimVersion`, and re-validated. The audit event records before, after, actor, role, evidence and version. Version 1 is never modified.
- **Edit:** approve with `edited_value`. It goes through the same checks and is recorded as edited.
- **Reject:** the proposal is marked rejected, with an approval row and an audit event. The claim is untouched.
- **Reassess:** the full orchestrator run on the current version. Superseded proposals are retired.

## 6. Data model — `app/models/models.py`

Reference: `Payer`, `Provider`, `Patient`, `InsurancePolicy`, `ClinicalDocument`, `AuthorizationRecord`, `PayerRule`, `CodingReference`, `ValidationRule`.
Claims: `Claim` (current working state, status, score, assessment, `ground_truth` used by the benchmark only), `ClaimLineItem`, `ClaimVersion` (immutable snapshots).
Execution: `AgentTask`, `AgentRun`, `ToolInvocation`, `AgentMessage`, `ValidationResult`.
Governance: `CorrectionProposal`, `CorrectionApproval`, `AuditEvent`, `SimulationRun`.
Indexes cover the claim status, the patient/provider/date duplicate key, the validation run, and audit time.

`ground_truth` is never passed to agents, prompts or the engine. Only `benchmark.py` reads it, to score detections.

## 7. API

REST under `/api` as specified (`claims`, `analyze`, `reassess`, `validation`, `corrections` approve/reject, `simulation`, `agents`, `agents/activity`, `analytics`, `audit`), plus `/api/health`, `/api/demo/load`, `/api/corrections`, `/api/rules`. Errors are 404 / 403 / 409 / 422 with Pydantic validation.
WebSocket `/ws/claimguard` sends a `hello` with current agent statuses and recent events, then batched events: `agent_status`, `task_assigned`, `agent_message`, `agent_run`, `tool_call`, `conflict`, `audit`, `claim_status`, `simulation`, `dataset_loaded`.

## 8. Known limitations

- Provider integrations are untested against live APIs (none was reachable while building).
- One shared SQLAlchemy session per simulation across asyncio tasks. Fine on a single-process demo; would need per-claim sessions under real concurrency.
- Identity and roles are demo headers, not authentication.
- The UI components are written in shadcn/ui style (cva + tailwind-merge) by hand, because the shadcn CLI registry was unreachable from the build environment.
