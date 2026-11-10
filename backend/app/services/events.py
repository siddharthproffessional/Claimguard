"""Live event bus and the Recorder that persists every agent action.

Nothing reaches the UI unless it was first written here by real backend execution.
"""
import asyncio
import itertools
import time
from collections import deque
from datetime import datetime, timezone

from app.models import models as m

AGENT_KEYS = ["orchestrator", "intake", "eligibility", "documentation", "coding", "authorization",
              "fraud_duplicate", "compliance", "recovery", "independent_reviewer"]


class EventBus:
    def __init__(self):
        self.subscribers: set[asyncio.Queue] = set()
        self.recent = deque(maxlen=2000)
        self._seq = itertools.count(1)
        self.reset_status()

    def reset_status(self):
        self.agent_status = {k: {"agent": k, "status": "idle", "claim_id": None, "updated": None} for k in AGENT_KEYS}

    def subscribe(self):
        q = asyncio.Queue(maxsize=20000)
        self.subscribers.add(q)
        return q

    def unsubscribe(self, q):
        self.subscribers.discard(q)

    def publish(self, type_, **data):
        evt = {"type": type_, "seq": next(self._seq), "ts": datetime.now(timezone.utc).isoformat(), **data}
        self.recent.append(evt)
        if type_ == "agent_status" and data.get("agent") in self.agent_status:
            self.agent_status[data["agent"]] = {"agent": data["agent"], "status": data.get("status"),
                                                "claim_id": data.get("claim_id"), "updated": evt["ts"]}
        for q in list(self.subscribers):
            try:
                q.put_nowait(evt)
            except asyncio.QueueFull:
                pass
        return evt


bus = EventBus()


class Recorder:
    """Persists tasks, messages, runs, tool calls and audit events for one claim, and emits them live."""

    def __init__(self, db, claim_id=None, simulation_id=None):
        self.db, self.claim_id, self.simulation_id = db, claim_id, simulation_id

    def status(self, agent, status):
        bus.publish("agent_status", agent=agent, status=status, claim_id=self.claim_id)

    def task(self, agent, description):
        t = m.AgentTask(claim_id=self.claim_id, simulation_id=self.simulation_id, agent=agent, description=description)
        self.db.add(t)
        self.db.flush()
        bus.publish("task_assigned", agent=agent, claim_id=self.claim_id, description=description, task_id=t.id)
        return t

    def task_done(self, task, status="completed"):
        task.status = status
        task.completed_at = m.utcnow()

    def message(self, sender, recipient, msg_type, content, payload=None):
        msg = m.AgentMessage(claim_id=self.claim_id, simulation_id=self.simulation_id, sender=sender, recipient=recipient,
                             msg_type=msg_type, content=content, payload=payload)
        self.db.add(msg)
        self.db.flush()
        bus.publish("agent_message", sender=sender, recipient=recipient, msg_type=msg_type, content=content,
                    claim_id=self.claim_id, message_id=msg.id)
        return msg

    def run_start(self, agent, iteration=1):
        run = m.AgentRun(claim_id=self.claim_id, simulation_id=self.simulation_id, agent=agent, iteration=iteration, status="working")
        self.db.add(run)
        self.db.flush()
        run._t0 = time.perf_counter()
        self.status(agent, "reassessment" if iteration > 1 else "working")
        return run

    def run_finish(self, run, status, output=None, ai_used=False, ai_note="", error=None, live_status=None):
        run.status = status
        run.output = output
        run.ai_used = ai_used
        run.ai_note = ai_note
        run.error = error
        run.duration_ms = round((time.perf_counter() - run._t0) * 1000, 2)
        self.db.flush()
        self.status(run.agent, live_status or status)
        bus.publish("agent_run", agent=run.agent, claim_id=self.claim_id, status=status, iteration=run.iteration,
                    duration_ms=run.duration_ms, ai_used=ai_used, run_id=run.id,
                    summary=(output or {}).get("summary") if isinstance(output, dict) else None)

    def tool(self, agent, run, name, fn, **args):
        t0 = time.perf_counter()
        ok, result, err = True, None, None
        try:
            result = fn()
        except Exception as e:  # tool failure is recorded, then surfaced to the agent
            ok, err = False, e
        dur = round((time.perf_counter() - t0) * 1000, 3)
        summary = (f"ERROR: {err}" if err else str(result))[:400]
        inv = m.ToolInvocation(agent_run_id=run.id if run is not None else None, claim_id=self.claim_id, agent=agent, tool=name,
                               args=args, result_summary=summary, ok=ok, duration_ms=dur)
        self.db.add(inv)
        bus.publish("tool_call", agent=agent, claim_id=self.claim_id, tool=name, ok=ok, duration_ms=dur, result=summary[:160])
        if err:
            raise err
        return result

    def audit(self, event_type, actor, actor_type, summary, details=None, claim_id=None):
        ev = m.AuditEvent(claim_id=claim_id or self.claim_id, simulation_id=self.simulation_id, event_type=event_type,
                          actor=actor, actor_type=actor_type, summary=summary, details=details)
        self.db.add(ev)
        self.db.flush()
        bus.publish("audit", event_type=event_type, actor=actor, actor_type=actor_type, summary=summary,
                    claim_id=claim_id or self.claim_id, audit_id=ev.id)
        return ev
