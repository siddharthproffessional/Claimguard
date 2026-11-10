"""Central configuration. Everything is environment-driven; no secrets in code."""
import json
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]  # .../claimguard
load_dotenv(ROOT / ".env")

# Readiness score weights (must sum to 100). Override with SCORING_WEIGHTS='{"eligibility": 25, ...}'
DEFAULT_WEIGHTS = {
    "eligibility": 20,
    "documentation": 20,
    "coding": 20,
    "authorization": 15,
    "billing": 15,
    "compliance": 10,
}

# SYNTHETIC ASSUMPTION: manual rework minutes per failed rule. Not measured from any real provider.
DEFAULT_EFFORT_MINUTES = {
    "ELIG-001": 6, "ELIG-002": 8, "ELIG-003": 20, "ELIG-004": 15,
    "DOC-001": 12, "DOC-002": 25, "COD-001": 10, "COD-002": 10, "COD-003": 25,
    "AUTH-001": 18, "AUTH-002": 30, "DUP-001": 15, "DUP-002": 15,
    "BILL-001": 5, "BILL-002": 12, "COMP-001": 5, "COMP-002": 10, "COV-001": 30,
}


def _json_env(name, default):
    raw = os.getenv(name)
    if not raw:
        return dict(default)
    try:
        val = json.loads(raw)
        return {**default, **val}
    except Exception:
        return dict(default)


class Settings:
    def __init__(self):
        self.reload()

    def reload(self):
        self.database_url = os.getenv("DATABASE_URL", f"sqlite:///{ROOT / 'backend' / 'claimguard.db'}")
        self.anthropic_api_key = os.getenv("ANTHROPIC_API_KEY", "")
        self.anthropic_base_url = os.getenv("CLAIMGUARD_ANTHROPIC_URL", "https://api.anthropic.com")
        self.claude_model_orchestrator = os.getenv("CLAUDE_MODEL_ORCHESTRATOR", "claude-fable-5-2")
        self.claude_model_specialist = os.getenv("CLAUDE_MODEL_SPECIALIST", "claude-fable-5-2")
        self.openai_api_key = os.getenv("OPENAI_API_KEY", "")
        self.openai_base_url = os.getenv("CLAIMGUARD_OPENAI_URL", "https://api.openai.com")
        self.openai_model = os.getenv("OPENAI_MODEL", "")
        # none | synthesis | full  (see docs/ARCHITECTURE.md "AI depth")
        self.ai_depth = os.getenv("AI_DEPTH", "synthesis")
        self.ai_timeout_s = float(os.getenv("AI_TIMEOUT_S", "45"))
        self.ai_max_tokens = int(os.getenv("AI_MAX_TOKENS", "1500"))
        self.agent_timeout_s = float(os.getenv("AGENT_TIMEOUT_S", "60"))
        self.max_iterations = int(os.getenv("MAX_AGENT_ITERATIONS", "3"))
        self.claim_concurrency = int(os.getenv("CLAIM_CONCURRENCY", "6"))
        self.reviewer_can_escalate = os.getenv("REVIEWER_CAN_ESCALATE", "true").lower() == "true"
        self.cors_origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",")]
        self.scoring_weights = _json_env("SCORING_WEIGHTS", DEFAULT_WEIGHTS)
        self.effort_minutes = _json_env("EFFORT_MINUTES", DEFAULT_EFFORT_MINUTES)

    @property
    def claude_enabled(self):
        return bool(self.anthropic_api_key)

    @property
    def openai_enabled(self):
        return bool(self.openai_api_key and self.openai_model)

    def effective_depth(self, requested=None):
        depth = requested or self.ai_depth
        if depth not in ("none", "synthesis", "full"):
            depth = "synthesis"
        if not (self.claude_enabled or self.openai_enabled):
            return "none"
        return depth


settings = Settings()
