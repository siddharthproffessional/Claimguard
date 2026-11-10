"""Export the seeded dataset and reference expected results to data/ and demo/.
Run from backend/:  python -m app.simulation.export"""
import asyncio
import json
import os
import tempfile

from app.config import ROOT
from app.simulation.seed import generate_dataset


def export_dataset(seed=42):
    ds = generate_dataset(seed)
    files = {
        "synthetic_claims/claims.json": ds["claims"],
        "synthetic_policies/patients.json": ds["patients"],
        "synthetic_policies/policies.json": ds["policies"],
        "synthetic_policies/authorizations.json": ds["authorizations"],
        "synthetic_documents/documents.json": ds["documents"],
        "reference_rules/coding_reference.json": ds["coding_references"],
        "reference_rules/payer_rules.json": ds["payer_rules"],
        "reference_rules/payers_providers.json": {"payers": ds["payers"], "providers": ds["providers"]},
    }
    for rel, data in files.items():
        p = ROOT / "data" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, indent=2))
    from app.validation.engine import RULES
    (ROOT / "data" / "reference_rules" / "validation_rules.json").write_text(json.dumps(RULES, indent=2))


async def expected(seed, mode):
    from app.database import db as database
    from app.simulation import benchmark
    database.configure("sqlite:///:memory:")
    database.init_db()
    s = database.SessionLocal()
    sim = benchmark.new_simulation(s, seed, "none", mode)
    s.close()
    r = await benchmark.run_simulation(sim.id, seed, "none", mode)
    for k in ("simulation_id",):
        r.pop(k)
    for side in ("baseline", "claimguard"):
        r[side].pop("processing_ms", None)
        r[side].pop("avg_ms_per_claim", None)
    return r


if __name__ == "__main__":
    os.environ.setdefault("CLAIMGUARD_RESULTS_DIR", tempfile.mkdtemp())
    export_dataset(42)
    out = ROOT / "demo" / "expected_results"
    out.mkdir(parents=True, exist_ok=True)
    for seed, mode, name in [(42, "manual", "seed42_deterministic_manual"), (42, "simulated_approve", "seed42_deterministic_simulated_operator"),
                             (7, "simulated_approve", "seed7_backup_deterministic_simulated_operator")]:
        (out / f"{name}.json").write_text(json.dumps(asyncio.run(expected(seed, mode)), indent=2))
    print("exported")
