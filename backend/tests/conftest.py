import asyncio
import os

os.environ["ANTHROPIC_API_KEY"] = ""
os.environ["OPENAI_API_KEY"] = ""
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
import tempfile
os.environ["CLAIMGUARD_RESULTS_DIR"] = tempfile.mkdtemp(prefix="cg_results_")

import pytest

from app.config import settings
from app.database import db as database


@pytest.fixture()
def db():
    settings.reload()
    database.configure("sqlite:///:memory:")
    database.init_db()
    s = database.SessionLocal()
    from app.simulation.benchmark import load_demo
    load_demo(s, 42)
    yield s
    s.close()


@pytest.fixture()
def run():
    return lambda coro: asyncio.run(coro)


@pytest.fixture()
def ai_on(monkeypatch):
    """Pretend both providers are configured; individual tests stub the HTTP layer."""
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    monkeypatch.setattr(settings, "openai_model", "test-reviewer")
    yield


def claim_where(db, pred):
    from app.models import models as m
    for c in db.query(m.Claim).order_by(m.Claim.seq):
        if pred(c.ground_truth or {}):
            return c
    raise LookupError("no claim matches")


def has_rule(rule):
    return lambda gt: any(i["rule"] == rule for i in gt.get("issues", []))


def only_rule(rule):
    return lambda gt: [i["rule"] for i in gt.get("issues", [])] == [rule]
