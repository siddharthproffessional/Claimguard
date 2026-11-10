# Data Assumptions

Everything in ClaimGuard's dataset is **invented**. There are no real patients, providers, payers or medical records. Every clinical document is headed `[SYNTHETIC DOCUMENT - NOT A REAL MEDICAL RECORD]`.

## Generator — `backend/app/simulation/seed.py`

- Deterministic for a given seed (`random.Random(seed)`). `generate_dataset(42)` always returns identical data, and a test checks this.
- **The issue mix is fixed by design; the seed changes which claims carry which issues.** Seeds 42 and 7 therefore produce the same aggregate benchmark numbers on different claims.
- 100 claims, about 92 patients, 3 payers, 4 providers, about 104 documents, about 44 authorizations.

| Category | Claims | Labelled rules | Fixable in-system |
|---|---|---|---|
| Clean | 36 (incl. 2 same-day "near duplicates" that are legitimately different services) | — | — |
| Missing documentation | 10 | DOC-001 (+ BILL-001 on 3) | 6 (document exists in repository) |
| Eligibility | 10 | ELIG-002 ×4 (transposed policy no.), ELIG-003 ×3 (coverage lapsed), ELIG-001 ×3 | 7 |
| Authorization | 10 | AUTH-001 ×7 (4 on file, unreferenced), AUTH-002 ×3 (expired) | 4 |
| Coding | 10 | COD-001 ×4, COD-002 ×3, COD-003 ×3 | 5 (document states the valid code) |
| Coverage | 5 | COV-001 (plan exclusion) | 0 |
| Billing | 5 | BILL-001 ×3, BILL-002 ×2 | 3 |
| Conflicting information | 6 | DOC-002 ×3 (structured), AI-NARRATIVE ×3 (free text only) | 0 |
| Incomplete fields | 2 | COMP-001 (place of service) | needs manual entry |
| Duplicates | 6 | DUP-002 ×6 (2 also DUP-001) | 0 |

Total: 69 labelled issues across 64 claims.

## Codes and rules

- **Diagnosis codes** use real ICD-10-CM formatting for 14 common conditions, but the **compatibility table is a demo assumption**, not coding guidance.
- **Procedure codes are synthetic** (`SP1001`…`SP7002`) and deliberately not CPT/HCPCS, so nothing implies certified coding. Prices and unit limits are invented.
- **Payer rules** (required documents per service category; prior authorization for imaging, surgery and major diagnostics; Meridian also requires it for physical therapy) are synthetic and do not represent any insurer or jurisdiction.

## Benchmark — `backend/app/simulation/benchmark.py`

- **Baseline:** a conventional scrubber running 6 claim-level rules (COMP-001, ELIG-001, COD-001, COD-002, BILL-001, DUP-001). No policy, document, authorization or payer-rule lookups, no combination-duplicate check, no corrections.
- **ClaimGuard:** the full pipeline. "Detected" means the claim's latest validation failed the labelled rule, or (for AI-NARRATIVE) the Documentation Agent's AI raised a concern on it.
- **False-positive claim:** a ground-truth-clean claim not marked READY.
- **Simulated operator** (`operator_mode=simulated_approve`): a clearly labelled stand-in that approves every proposal that passed dry-run validation, to measure the *ceiling* of in-system recovery. It is not a claim that humans would approve all of them.
- **Effort minutes** per rule (`EFFORT_MINUTES`) are configured assumptions, not measurements.
- **Caveat:** the rules and the generator share one issue taxonomy, so deterministic recall on this data is an upper bound. Nothing here supports a claim about real-world rejection reduction.
