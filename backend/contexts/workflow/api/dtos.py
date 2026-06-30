"""Workflow API DTOs (Phase 4 — Slice 4.0).

Strict ``extra=forbid`` schemas. Each request/response is part of the
v2.0.0 contract package — names mirror ``contracts/generate.py``.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class StartWorkflowRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    definition_name: str = Field(..., min_length=1, max_length=128)
    definition_version: Optional[int] = Field(default=None, ge=1)
    payload: dict = Field(default_factory=dict)
    correlation_id: Optional[str] = Field(default=None, max_length=128)


class CancelWorkflowRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(..., min_length=1, max_length=512)


class SuspendWorkflowRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(..., min_length=1, max_length=512)


class ReactivateWorkflowRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: Optional[str] = Field(default=None, max_length=512)


class CompleteTaskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    payload: dict = Field(default_factory=dict)


class WorkflowInstanceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    instance_id: str
    definition_name: str
    definition_version: int
    business_state: str
    lifecycle: str
    initiator_id: str
    tenant_id: str
    country_code: str
    correlation_id: Optional[str] = None
    payload: dict
    version: int
    schema_version: int
    last_command: Optional[str] = None
    last_actor: Optional[str] = None
    last_transitioned_at: Optional[str] = None
    terminated_at: Optional[str] = None
    suspended_reason: Optional[str] = None
    created_at: str


class WorkflowInstanceListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[WorkflowInstanceResponse]
    count: int


class WorkflowTaskResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_id: str
    instance_id: str
    definition_name: str
    title: str
    state: str
    assigned_to_role: Optional[str] = None
    assigned_to_principal: Optional[str] = None
    claimed_by: Optional[str] = None
    claimed_at: Optional[str] = None
    completed_by: Optional[str] = None
    completed_at: Optional[str] = None
    completion_payload: dict
    due_at: Optional[str] = None
    cancelled_reason: Optional[str] = None
    tenant_id: str
    country_code: str
    version: int
    schema_version: int
    created_at: str


class WorkflowTaskListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[WorkflowTaskResponse]
    count: int


class WorkflowTimerResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    timer_id: str
    instance_id: str
    definition_name: str
    fire_at: str
    state: str
    command_on_fire: str
    payload_on_fire: dict
    fired_at: Optional[str] = None
    cancelled_at: Optional[str] = None
    cancelled_reason: Optional[str] = None
    tenant_id: str
    country_code: str
    version: int
    schema_version: int
    created_at: str


class WorkflowTimerListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[WorkflowTimerResponse]
    count: int


class WorkflowReplayResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    instance_id: str
    replay_event_count: int
    business_state: str
    lifecycle: str
    version: int
    matches_committed: bool


class WorkflowDefinitionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    version: int
    description: str
    initial_state: str
    states: list[str]
    terminal_states: list[str]
    transition_count: int


class WorkflowDefinitionListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[WorkflowDefinitionResponse]
    count: int
