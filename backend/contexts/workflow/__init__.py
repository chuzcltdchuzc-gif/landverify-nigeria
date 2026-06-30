"""Workflow bounded context (Phase 4 — Slice 4.0 Foundation).

Implements the constitutional Workflow Engine: definitions, instances,
tasks, timers, and compensation logging. Per ADR-0019 and PHASE4_SPEC.

Slice 4.0 scope (foundation only):
* Workflow Definition (immutable, JSON-loaded, cycle-checked)
* Workflow Instance (event-sourced, replayable, pure apply())
* Task / Timer / CompensationLog aggregates
* Workflow Engine (start / apply_command / fire_timer / replay /
  cancel / suspend / reactivate)
* Saga composer skeleton (DSL interpreter for ``spawn`` directives)
* Mongo repositories + admin HTTP surface
* One minimal projector (workflow_instance read model)
* echo.v1 demonstration workflow definition

NOT in 4.0 scope (deferred to 4.2+):
* Consent / Community / Inheritance sub-contexts
* Survey assignment, attestation, court order, share-calculation
* Business-facing UI / SDK clients
"""
