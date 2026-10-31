"""Recall reads worked/failed from lessons only, never from past decision traces.
Real Meko returns those traces from context_search; this is the exact shape seen live."""
import asyncio

from app.agents import recall as recall_mod
from app.models import Incident, MemoryItem

LESSON = MemoryItem(source="knowledge_base", score=0.9999, text=(
    "[seeded demo history] Lesson for checkout (v1.6): when checkout returns 503s because DB connections "
    "run out. The fix that worked was pause_batch_job (pause the export job). These made it worse or "
    "failed: raise_pool_size (DB hit its connection cap), restart_service (reconnect storm)."))
TRACE = MemoryItem(source="conversation", score=0.9999, text=(
    "checkout returns 503s because DB connections run out |  | "
    "match=True worked=['pause_batch_job'] failed=['raise_pool_size', 'restart_service']"))


def test_decision_traces_do_not_turn_the_right_fix_into_a_failure(monkeypatch):
    async def fake_recall(query, agent="recall"):
        return [LESSON, TRACE, TRACE], None
    monkeypatch.setattr(recall_mod.memory, "recall", fake_recall)
    r = asyncio.run(recall_mod.recall(Incident(signature="db pool"), "v1.6"))
    assert r.match and r.worked == ["pause_batch_job"]
    assert r.failed == ["raise_pool_size", "restart_service"]
    assert len(r.items) == 3                     # traces are still shown in the recall panel
