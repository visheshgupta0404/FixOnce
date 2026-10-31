"""Shared data shapes. This file IS the contract between the three of us.
Change it only together, and promote the change to the build datapack."""
from __future__ import annotations

import time
import uuid
from typing import Literal, Optional

from pydantic import BaseModel, Field

SafeAction = Literal["pause_batch_job", "raise_pool_size", "scale_up", "rollback_last_deploy", "restart_service"]
SAFE_ACTIONS: list[str] = ["pause_batch_job", "raise_pool_size", "scale_up", "rollback_last_deploy", "restart_service"]

ACTION_LABELS = {
    "pause_batch_job": "Pause the running batch/export job",
    "raise_pool_size": "Raise the DB connection pool size",
    "scale_up": "Add more service replicas",
    "rollback_last_deploy": "Roll back to the previous version",
    "restart_service": "Restart the service",
}

Status = Literal["open", "investigating", "waiting_human", "fixing", "resolved", "escalated"]


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:6]}"


class MemoryItem(BaseModel):
    """Exactly what Meko returned (or what we stored). Shown as-is in the recall panel (A4, A5)."""
    id: Optional[str] = None
    text: str
    score: Optional[float] = None
    source: str = "memory"          # memory | knowledge_base | conversation | stored
    promoted: Optional[bool] = None
    metadata: dict = Field(default_factory=dict)


class RecallResult(BaseModel):
    meko_enabled: bool
    match: bool = False
    confidence: float = 0.0
    items: list[MemoryItem] = Field(default_factory=list)
    worked: list[str] = Field(default_factory=list)
    failed: list[str] = Field(default_factory=list)
    learned_on_version: Optional[str] = None
    stale: bool = False
    error: Optional[str] = None


class Attempt(BaseModel):
    action: str
    approved_by: Optional[str] = None
    result: Literal["pending", "worked", "failed", "blocked"] = "pending"
    note: str = ""
    at: float = Field(default_factory=time.time)


class Incident(BaseModel):
    id: str = Field(default_factory=lambda: new_id("inc"))
    service: str = "checkout"
    version: str = ""
    status: Status = "open"
    symptoms: str = ""
    signature: str = ""
    summary: str = ""
    opened_at: float = Field(default_factory=time.time)
    resolved_at: Optional[float] = None
    meko_enabled: bool = True
    recall: Optional[RecallResult] = None
    proposed_action: Optional[str] = None
    proposal_reason: str = ""
    blocked_reason: str = ""
    attempts: list[Attempt] = Field(default_factory=list)
    stored: list[MemoryItem] = Field(default_factory=list)
    lesson_ids: list[str] = Field(default_factory=list)
    conversation_id: Optional[str] = None
    timeline: list[dict] = Field(default_factory=list)
    simulation: bool = True

    def log(self, who: str, what: str) -> None:
        self.timeline.append({"t": time.time(), "who": who, "what": what})

    @property
    def time_to_fix_s(self) -> Optional[float]:
        return None if self.resolved_at is None else round(self.resolved_at - self.opened_at, 1)


class Decision(BaseModel):
    choice: Literal["apply", "why", "escalate"]
    by: str = "on-call"


class MekoSetting(BaseModel):
    enabled: bool


class CorrectLesson(BaseModel):
    text: str


class PromoteLesson(BaseModel):
    confirmed_by: str = "on-call"


class Ask(BaseModel):
    question: str
