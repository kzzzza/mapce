"""Pydantic models for the local MAPCE service API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ErrorResponse(BaseModel):
    status: Literal["error"] = "error"
    error_code: str
    message: str


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    service_id: str
    version: str
    pid: int
    data_dir_hash: str
    uptime_seconds: float
    embedding_loaded: bool


class ToolCallRequest(BaseModel):
    arguments: dict[str, Any] = Field(default_factory=dict)


class JobSubmitRequest(BaseModel):
    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class JobRecord(BaseModel):
    job_id: str
    tool: str
    arguments: dict[str, Any]
    state: Literal[
        "queued", "running", "complete", "failed", "cancelling", "cancelled"
    ]
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    result: dict[str, Any] | None = None
    error: str | None = None
