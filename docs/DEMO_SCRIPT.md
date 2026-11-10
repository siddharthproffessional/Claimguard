# Demo Script: Operation Zero Rejection (4 minutes)

Claim IDs below are for **seed 42**. Reset with **Reload data** (seed 42) before each rehearsal.

## Pre-flight (before going on stage)

1. Backend running with keys in `.env`; sidebar shows **Claude: configured** and **OpenAI reviewer: configured**.
2. **Time a full AI run in rehearsal.** `synthesis` makes about 230 model calls. At `CLAIM_CONCURRENCY=6` and ~4 s per call, that is roughly 2–3 minutes, which is too slow for the 1:00–1:30 slot. Pick one plan:
   - **Plan A (recommended):** run the 100 claims at **Deterministic only** live (~3 s, all real), then show AI live on single claims at 2:30.
   - **Plan B:** if your rehearsal run finishes in under 60 s (raise `CLAIM_CONCURRENCY` to 12–16, use a faster `CLAUDE_MODEL_SPECIALIST`), run the whole operation at **Synthesis** live.
3. Open tabs: Command Centre, Claims → CLM-0014, Claims → CLM-0028, Correction Workspace, Analytics, Audit.
4. Set the role to **Billing operator**.
5. Backup recording: screen-capture a full rehearsal.

## Run of show

**0:00–0:30 · The problem** *(Command Centre, before running)*
Claims bounce for preventable reasons: a transposed policy number, a missing note, an authorization nobody linked. Each one costs rework and delays payment. ClaimGuard catches them before submission.

**0:30–1:00 · Introduce ClaimGuard**
100 synthetic claims from a fictional provider. Point at the ten agent tiles: eight specialists, the orchestrator, and an independent reviewer from a different AI vendor. Readiness is decided by deterministic rules, never by the model.

**1:00–1:30 · Start Operation Zero Rejection**
Press **Start operation**. Watch the tiles flip *Working → Completed*, *Reassessment* and *Conflict detected* with real claim IDs, and the counters climb (about 1,000 agent runs, 2,500 tool calls). Say: "Nothing here is animated; every status comes from the backend."

**1:30–2:30 · Agent collaboration** *(Claims → CLM-0028)*
- The Authorization Agent first reported a **valid** authorization. The Eligibility Agent found that **coverage had lapsed** before the date of service.
- The orchestrator detected the conflict, relayed Eligibility's evidence, and Authorization **revised its position in iteration 2** (*"on file but not sufficient"*). The conflict is marked *resolved*; the claim goes to human review.
- Scroll to **Agent communication** for the message trail. Optional: Agent Control Room → filter `CLM-0028`.

**2:30–3:00 · Independent verification** *(Claims → CLM-0014, AI depth Synthesis → Request reassessment)*
- The rules alone pass this claim: every field is valid. The clinical note says the patient **did not attend**.
- The Documentation Agent's Claude reading raises it, the orchestrator logs an *AI vs rules* conflict, and the claim escalates to **Human review** (a *"rules alone: ready"* badge sits next to the status).
- The AI assessment panel shows Claude's synthesis and **OpenAI's verdict**. Any disagreement is in Audit → *Model disagreements*.
- *Fallback if a provider is down:* the panel shows `unavailable: …`, the claim keeps its deterministic status, and the audit shows `ai_provider_failure`. That is itself a talking point.

**3:00–3:30 · Measured outcomes** *(Analytics)*
Same 100 claims: the baseline scrubber detected **20 of 69** labelled issues and let **44** problem claims through; ClaimGuard detected **66 of 69** deterministically (69 with AI reading the notes) with **0 false positives**, plus 28 validated corrections. Point at the **assumptions** card: synthetic data, not a real-world rejection rate.

**3:30–4:00 · Human control** *(Correction Workspace)*
Approve **CLM-0009**'s policy-number correction (`NOR-5081938 → NOR-5081983`, evidence: policy registry). The card shows **re-validated as v2: Requires correction 95 → Ready 100**. Open **Audit → Human decisions**: actor, role, before/after, evidence. Close: "The AI finds and explains. People decide."

## Backup scenario

If the main dataset is in a bad state: **Reload data** with **seed 7** and run again. The aggregate numbers are identical by design, on different claims; see `demo/expected_results/seed7_backup_deterministic_simulated_operator.json`. Use Claims filtered to *Human review* to find a conflict claim live.

## Useful seed-42 claims

| Claim | Shows |
|---|---|
| CLM-0009, 0025, 0037, 0060 | Transposed policy number → one-click registry correction → READY |
| CLM-0010 | Missing clinical note found in the repository → attach → READY |
| CLM-0005 | Invalid diagnosis code → correction needs **Certified coder** (try it as Billing operator: 403) |
| CLM-0028, CLM-0073 | Authorization vs Eligibility conflict, resolved by reassessment |
| CLM-0091 | Authorization vs Compliance (plan exclusion) conflict |
| CLM-0001, 0023, 0055 | Document names a different procedure → Coding revises → human review |
| CLM-0014, 0034, 0078 | Problem visible only in the free-text note (needs AI) |
| CLM-0081, 0092 | Potential duplicate (same control number) |
