"""Vercel entry point: exposes the ClaimGuard FastAPI app as a Python function."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))

from app.main import app  # noqa: E402,F401
