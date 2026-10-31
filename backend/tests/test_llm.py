"""When Gemini is down or slow, the rule-based stand-in answers and the failure is counted."""
import asyncio
import time

from app import llm as llm_mod


def test_gemini_failure_falls_back_and_cools_down(monkeypatch):
    calls = []

    def broken(prompt, schema):
        calls.append(1)
        raise RuntimeError("503 UNAVAILABLE")

    llm = llm_mod.LLM(mode="gemini")
    monkeypatch.setattr(llm, "_call_gemini", broken)
    schema = llm_mod.obj({"signature": {"type": "string"}})
    out = asyncio.run(llm.json("triage", "p", schema, lambda: {"signature": "rule-based"}))
    assert out == {"signature": "rule-based"} and len(calls) == 2
    assert llm.fallbacks == 1 and "503" in llm.last_error
    asyncio.run(llm.json("fixer", "p", schema, lambda: {"signature": "again"}))
    assert len(calls) == 2 and llm.fallbacks == 2      # cooling down: Gemini not called again


def test_slow_gemini_times_out(monkeypatch):
    monkeypatch.setattr(llm_mod, "TIMEOUT_S", 0.1)
    llm = llm_mod.LLM(mode="gemini")
    monkeypatch.setattr(llm, "_call_gemini", lambda p, s: time.sleep(0.5) or {"signature": "late"})
    out = asyncio.run(llm.json("triage", "p", llm_mod.obj({"signature": {"type": "string"}}), lambda: {"signature": "rb"}))
    assert out == {"signature": "rb"} and "0s" in llm.last_error
