"""FastAPI router for the Workflow context — ``/api/v1/workflow/*``.

Phase 4 Slice 4.0 surface (foundation, admin-oriented):

* GET    /definitions                   — list loaded definitions
* POST   /instances                     — start a workflow (privileged roles)
* GET    /instances                     — list instances (scoped)
* GET    /instances/{id}                — read instance
* POST   /instances/{id}/cancel         — cancel instance
* POST   /instances/{id}/suspend        — suspend instance (super_admin)
* POST   /instances/{id}/reactivate     — reactivate instance (super_admin)
* GET    /tasks                         — list tasks (scoped)
* GET    /tasks/{id}                    — read task
* POST   /tasks/{id}/claim              — claim task
* POST   /tasks/{id}/complete           — complete task
* GET    /timers                        — list timers
* GET    /timers/{id}                   — read timer
* POST   /admin/instances/{id}/replay   — replay instance from outbox (super_admin)
* POST   /admin/timers/{id}/fire        — manually fire a timer (super_admin)

Business workflow APIs (consent, community, inheritance) are
constitutionally deferred to slices 4.2+.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Path, Query, status

from contexts.workflow.api.dtos import (
    CancelWorkflowRequest,
    CompleteTaskRequest,
    ReactivateWorkflowRequest,
    StartWorkflowRequest,
    SuspendWorkflowRequest,
    WorkflowDefinitionListResponse,
    WorkflowDefinitionResponse,
    WorkflowInstanceListResponse,
    WorkflowInstanceResponse,
    WorkflowReplayResponse,
    WorkflowTaskListResponse,
    WorkflowTaskResponse,
    WorkflowTimerListResponse,
    WorkflowTimerResponse,
)
from contexts.workflow.application.engine import TaskService, WorkflowEngine
from contexts.workflow.domain.task import Task
from contexts.workflow.domain.timer import Timer
from contexts.workflow.domain.workflow_instance import WorkflowInstance
from contexts.workflow.ports.repository import (
    DefinitionLoader,
    InstanceSpec,
    TaskSpec,
    TimerSpec,
)
from kernel.authorization.pep import enforce, require_auth
from kernel.errors.problem import not_found
from kernel.persistence.context import ExecutionContext

router = APIRouter(prefix="/v1/workflow", tags=["workflow"])

_engine: Optional[WorkflowEngine] = None
_tasks: Optional[TaskService] = None
_definitions: Optional[DefinitionLoader] = None


def configure_router(engine: WorkflowEngine, tasks: TaskService,
                       definitions: DefinitionLoader) -> None:
    global _engine, _tasks, _definitions
    _engine = engine
    _tasks = tasks
    _definitions = definitions


def _eng() -> WorkflowEngine:
    if _engine is None:
        raise RuntimeError("workflow engine not configured")
    return _engine


def _tsk() -> TaskService:
    if _tasks is None:
        raise RuntimeError("workflow task service not configured")
    return _tasks


def _defs() -> DefinitionLoader:
    if _definitions is None:
        raise RuntimeError("workflow definition loader not configured")
    return _definitions


# ---- Projections ---------------------------------------------------------

def _instance_to_dto(inst: WorkflowInstance) -> WorkflowInstanceResponse:
    return WorkflowInstanceResponse(
        instance_id=inst.instance_id,
        definition_name=inst.definition_name,
        definition_version=inst.definition_version,
        business_state=inst.business_state,
        lifecycle=inst.lifecycle,
        initiator_id=inst.initiator_id,
        tenant_id=inst.tenant_id,
        country_code=inst.country_code,
        correlation_id=inst.correlation_id,
        payload=inst.payload,
        version=inst.version,
        schema_version=inst.schema_version,
        last_command=inst.last_command,
        last_actor=inst.last_actor,
        last_transitioned_at=inst.last_transitioned_at,
        terminated_at=inst.terminated_at,
        suspended_reason=inst.suspended_reason,
        created_at=inst.created_at,
    )


def _task_to_dto(task: Task) -> WorkflowTaskResponse:
    return WorkflowTaskResponse(
        task_id=task.task_id,
        instance_id=task.instance_id,
        definition_name=task.definition_name,
        title=task.title,
        state=task.state,
        assigned_to_role=task.assigned_to_role,
        assigned_to_principal=task.assigned_to_principal,
        claimed_by=task.claimed_by,
        claimed_at=task.claimed_at,
        completed_by=task.completed_by,
        completed_at=task.completed_at,
        completion_payload=task.completion_payload,
        due_at=task.due_at,
        cancelled_reason=task.cancelled_reason,
        tenant_id=task.tenant_id,
        country_code=task.country_code,
        version=task.version,
        schema_version=task.schema_version,
        created_at=task.created_at,
    )


def _timer_to_dto(t: Timer) -> WorkflowTimerResponse:
    return WorkflowTimerResponse(
        timer_id=t.timer_id,
        instance_id=t.instance_id,
        definition_name=t.definition_name,
        fire_at=t.fire_at,
        state=t.state,
        command_on_fire=t.command_on_fire,
        payload_on_fire=t.payload_on_fire,
        fired_at=t.fired_at,
        cancelled_at=t.cancelled_at,
        cancelled_reason=t.cancelled_reason,
        tenant_id=t.tenant_id,
        country_code=t.country_code,
        version=t.version,
        schema_version=t.schema_version,
        created_at=t.created_at,
    )


# ---- Definitions ---------------------------------------------------------

@router.get("/definitions", response_model=WorkflowDefinitionListResponse)
async def list_definitions(_ctx: ExecutionContext = Depends(require_auth)):
    await enforce("workflow.instance.list",
                   resource={"resource_type": "workflow_definition"})
    items = []
    for d in _defs().list_definitions():
        items.append(WorkflowDefinitionResponse(
            name=d.name, version=d.version, description=d.description,
            initial_state=d.initial_state,
            states=sorted(d.states.keys()),
            terminal_states=sorted([s.name for s in d.states.values()
                                     if s.is_terminal]),
            transition_count=len(d.transitions)))
    return WorkflowDefinitionListResponse(items=items, count=len(items))


# ---- Instances -----------------------------------------------------------

@router.post("/instances", status_code=status.HTTP_201_CREATED,
              response_model=WorkflowInstanceResponse)
async def start_workflow(payload: StartWorkflowRequest,
                            ctx: ExecutionContext = Depends(require_auth)):
    await enforce("workflow.instance.start",
                   resource={"resource_type": "workflow_instance"})
    instance = await _eng().start_workflow(
        definition_name=payload.definition_name,
        definition_version=payload.definition_version,
        initiator_id=ctx.principal_id,
        payload=payload.payload,
        correlation_id=payload.correlation_id,
    )
    return _instance_to_dto(instance)


@router.get("/instances", response_model=WorkflowInstanceListResponse)
async def list_instances(
    definition_name: Optional[str] = Query(default=None),
    business_state: Optional[str] = Query(default=None),
    lifecycle: Optional[str] = Query(default=None),
    correlation_id: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    _ctx: ExecutionContext = Depends(require_auth),
):
    await enforce("workflow.instance.list",
                   resource={"resource_type": "workflow_instance"})
    spec = InstanceSpec(definition_name=definition_name,
                          business_state=business_state,
                          lifecycle=lifecycle,
                          correlation_id=correlation_id,
                          limit=limit)
    items = await _eng()._instances.list(spec)
    dtos = [_instance_to_dto(i) for i in items]
    return WorkflowInstanceListResponse(items=dtos, count=len(dtos))


@router.get("/instances/{instance_id}",
             response_model=WorkflowInstanceResponse)
async def get_instance(instance_id: str = Path(...),
                        _ctx: ExecutionContext = Depends(require_auth)):
    await enforce("workflow.instance.read",
                   resource={"resource_type": "workflow_instance",
                             "resource_id": instance_id})
    inst = await _eng()._instances.get(instance_id)
    if inst is None:
        raise not_found(f"workflow instance {instance_id} not found",
                         code="workflow.instance.not_found")
    return _instance_to_dto(inst)


@router.post("/instances/{instance_id}/cancel",
              response_model=WorkflowInstanceResponse)
async def cancel_instance(payload: CancelWorkflowRequest,
                            instance_id: str = Path(...),
                            ctx: ExecutionContext = Depends(require_auth)):
    await enforce("workflow.instance.cancel",
                   resource={"resource_type": "workflow_instance",
                             "resource_id": instance_id})
    inst = await _eng().cancel(instance_id=instance_id,
                                  actor=ctx.principal_id,
                                  reason=payload.reason)
    return _instance_to_dto(inst)


@router.post("/instances/{instance_id}/suspend",
              response_model=WorkflowInstanceResponse)
async def suspend_instance(payload: SuspendWorkflowRequest,
                             instance_id: str = Path(...),
                             ctx: ExecutionContext = Depends(require_auth)):
    await enforce("workflow.instance.suspend",
                   resource={"resource_type": "workflow_instance",
                             "resource_id": instance_id})
    inst = await _eng().suspend(instance_id=instance_id,
                                   actor=ctx.principal_id,
                                   reason=payload.reason)
    return _instance_to_dto(inst)


@router.post("/instances/{instance_id}/reactivate",
              response_model=WorkflowInstanceResponse)
async def reactivate_instance(payload: ReactivateWorkflowRequest,
                                instance_id: str = Path(...),
                                ctx: ExecutionContext = Depends(require_auth)):
    await enforce("workflow.instance.reactivate",
                   resource={"resource_type": "workflow_instance",
                             "resource_id": instance_id})
    inst = await _eng().reactivate(instance_id=instance_id,
                                       actor=ctx.principal_id)
    _ = payload  # reactivate reason is optional, recorded via audit log
    return _instance_to_dto(inst)


# ---- Tasks ---------------------------------------------------------------

@router.get("/tasks", response_model=WorkflowTaskListResponse)
async def list_tasks(
    instance_id: Optional[str] = Query(default=None),
    state: Optional[str] = Query(default=None),
    assigned_to_role: Optional[str] = Query(default=None),
    assigned_to_principal: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    _ctx: ExecutionContext = Depends(require_auth),
):
    await enforce("workflow.task.list",
                   resource={"resource_type": "workflow_task"})
    spec = TaskSpec(instance_id=instance_id, state=state,
                      assigned_to_role=assigned_to_role,
                      assigned_to_principal=assigned_to_principal,
                      limit=limit)
    items = await _eng()._tasks.list(spec)
    dtos = [_task_to_dto(t) for t in items]
    return WorkflowTaskListResponse(items=dtos, count=len(dtos))


@router.get("/tasks/{task_id}", response_model=WorkflowTaskResponse)
async def get_task(task_id: str = Path(...),
                    _ctx: ExecutionContext = Depends(require_auth)):
    await enforce("workflow.task.read",
                   resource={"resource_type": "workflow_task",
                             "resource_id": task_id})
    task = await _eng()._tasks.get(task_id)
    if task is None:
        raise not_found(f"task {task_id} not found",
                         code="workflow.task.not_found")
    return _task_to_dto(task)


@router.post("/tasks/{task_id}/claim", response_model=WorkflowTaskResponse)
async def claim_task(task_id: str = Path(...),
                       ctx: ExecutionContext = Depends(require_auth)):
    await enforce("workflow.task.claim",
                   resource={"resource_type": "workflow_task",
                             "resource_id": task_id})
    task = await _tsk().claim(task_id=task_id, principal_id=ctx.principal_id)
    return _task_to_dto(task)


@router.post("/tasks/{task_id}/complete", response_model=WorkflowTaskResponse)
async def complete_task(payload: CompleteTaskRequest,
                          task_id: str = Path(...),
                          ctx: ExecutionContext = Depends(require_auth)):
    await enforce("workflow.task.complete",
                   resource={"resource_type": "workflow_task",
                             "resource_id": task_id})
    task = await _tsk().complete(task_id=task_id,
                                    principal_id=ctx.principal_id,
                                    payload=payload.payload)
    return _task_to_dto(task)


# ---- Timers --------------------------------------------------------------

@router.get("/timers", response_model=WorkflowTimerListResponse)
async def list_timers(
    instance_id: Optional[str] = Query(default=None),
    state: Optional[str] = Query(default=None),
    due_before: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    _ctx: ExecutionContext = Depends(require_auth),
):
    await enforce("workflow.timer.list",
                   resource={"resource_type": "workflow_timer"})
    spec = TimerSpec(instance_id=instance_id, state=state,
                       due_before=due_before, limit=limit)
    items = await _eng()._timers.list(spec)
    dtos = [_timer_to_dto(t) for t in items]
    return WorkflowTimerListResponse(items=dtos, count=len(dtos))


@router.get("/timers/{timer_id}", response_model=WorkflowTimerResponse)
async def get_timer(timer_id: str = Path(...),
                     _ctx: ExecutionContext = Depends(require_auth)):
    await enforce("workflow.timer.read",
                   resource={"resource_type": "workflow_timer",
                             "resource_id": timer_id})
    timer = await _eng()._timers.get(timer_id)
    if timer is None:
        raise not_found(f"timer {timer_id} not found",
                         code="workflow.timer.not_found")
    return _timer_to_dto(timer)


# ---- Admin endpoints -----------------------------------------------------

@router.post("/admin/instances/{instance_id}/replay",
              response_model=WorkflowReplayResponse)
async def replay_instance(instance_id: str = Path(...),
                            _ctx: ExecutionContext = Depends(require_auth)):
    await enforce("workflow.admin.replay",
                   resource={"resource_type": "workflow_instance",
                             "resource_id": instance_id})
    rebuilt = await _eng().replay(instance_id)
    if rebuilt is None:
        raise not_found(f"workflow instance {instance_id} has no events",
                         code="workflow.instance.not_found")
    committed = await _eng()._instances.get(instance_id)
    matches = (
        committed is not None
        and committed.business_state == rebuilt.get("business_state")
        and committed.lifecycle == rebuilt.get("lifecycle")
        and committed.version == rebuilt.get("version")
    )
    return WorkflowReplayResponse(
        instance_id=instance_id,
        replay_event_count=int(rebuilt.get("_replay_event_count", 0)),
        business_state=rebuilt.get("business_state", ""),
        lifecycle=rebuilt.get("lifecycle", ""),
        version=int(rebuilt.get("version", 0)),
        matches_committed=matches,
    )


@router.post("/admin/timers/{timer_id}/fire",
              response_model=WorkflowInstanceResponse)
async def fire_timer(timer_id: str = Path(...),
                       ctx: ExecutionContext = Depends(require_auth)):
    await enforce("workflow.admin.fire_timer",
                   resource={"resource_type": "workflow_timer",
                             "resource_id": timer_id})
    inst = await _eng().fire_timer(timer_id=timer_id, actor=ctx.principal_id)
    if inst is None:
        raise not_found(f"timer {timer_id} could not fire",
                         code="workflow.timer.not_found")
    return _instance_to_dto(inst)
