# ADR-0021 — Community Validation & Attestation (Phase 4)

* **Status:** DRAFT — pending operator approval
* **Phase:** 4 (Workflows · sub-context)
* **Depends on:** ADR-0019 (Workflow Engine), ADR-0020 (Consent Engine), ADR-0007 / ADR-0009 (Evidence)
* **Owns:** the community-attested validation sub-context — village elders, traditional authorities, surveyors, compliance officers, and the Surveyor General participating in a deterministic consensus process.

---

## 1. Context

In the operating jurisdictions, land claims are validated by **the
community that lives on the land**, not by a faceless registrar.
Village elders, traditional authorities, and neighbours observe and
attest. A claim that lacks community attestation may be legally
recorded but is socially unenforceable.

The Community Validation sub-context formalises this practice into
a deterministic workflow that:

- routes every claim through the appropriate community structure,
- captures attestations with the same legal rigor as Consent
  (ADR-0020),
- computes a deterministic consensus score,
- routes the claim through a final compliance + Surveyor General
  review chain.

Every step is replayable, append-only, and human-authoritative.

## 2. Decision

Implement a multi-workflow sub-context with the following pieces:

### 2.1 Workflows (state machines)

The sub-context houses six distinct `WorkflowDefinition`s. Each is a
peer; saga composition (ADR-0019 §2.7) links them.

#### 2.1.1 `survey_assignment.v1`

```
ASSIGNED ──▶ ACCEPTED ──▶ IN_FIELD ──▶ FIELD_COMPLETE ──▶ REPORT_PENDING
                                                              │
                                                              ▼
                                                    REPORT_SUBMITTED (terminal)
                                                              │
                                                              ▼ (consumed by community_validation)
            DECLINED (terminal — surveyor refuses)
            REASSIGNED (terminal — operator reassigns; spawns new instance)
            ABANDONED (terminal — timer fired)
```

#### 2.1.2 `community_validation.v1`

```
                       ┌──── CLARIFICATION_REQUESTED ──▶ CLARIFICATION_RESOLVED ──▶ (loops to ATTESTATION_OPEN)
                       │                                  │
INITIATED ──▶ ATTESTATION_OPEN ──▶ ATTESTATION_CLOSED ──▶ CONSENSUS_COMPUTED ──▶ ATTESTED (terminal)
                       │                                  │
                       │                                  └─▶ REJECTED (terminal · explicit dissent ≥ threshold)
                       │
                       └─▶ ESCALATED (terminal · sent to compliance_review)
```

#### 2.1.3 `compliance_review.v1`

```
QUEUED ──▶ UNDER_REVIEW ──▶ APPROVED (terminal — promotes to surveyor_general_review)
                  │
                  ├──▶ RETURNED (terminal — bounces back to community_validation w/ findings)
                  └──▶ REJECTED (terminal — final rejection at compliance layer)
```

#### 2.1.4 `surveyor_general_review.v1`

```
QUEUED ──▶ UNDER_REVIEW ──▶ APPROVED (terminal — emits registry.command.commit_parcel)
                  │
                  ├──▶ HELD_FOR_INFO (terminal · loops via clarification to community_validation)
                  └──▶ REJECTED (terminal — final rejection at SG layer)
```

#### 2.1.5 `attestation_appeal.v1`

```
FILED ──▶ HEARD ──▶ DECISION_DRAFTED ──▶ DECISION_FINAL (terminal)
            │
            └─▶ DISMISSED (terminal)
```

#### 2.1.6 `clarification.v1` (helper, embedded)

```
REQUESTED ──▶ RESPONSE_AWAITED ──▶ RESPONDED ──▶ CLOSED (terminal)
                      │
                      └─▶ TIMED_OUT (terminal — escalates to compliance)
```

### 2.2 Roles (Phase 4 RBAC)

| Role | Authority |
| --- | --- |
| `field_agent` | initiate community workflows (existing) |
| `surveyor` | execute `survey_assignment` |
| `village_elder` | attest in `community_validation` |
| `traditional_authority` | attest in `community_validation`, escalate |
| `community_representative` | attest in `community_validation` |
| `compliance_officer` | own `compliance_review`, may pause any workflow |
| `surveyor_general` | own `surveyor_general_review`; the only role that emits `registry.command.commit_parcel` |
| `super_admin` | break-glass on every workflow |

PEP rules per command are enumerated in `PHASE4_SPEC.md §6`. Every
attestation requires the actor to be holding a valid JWT AND the
attestation to be Evidence-backed.

### 2.3 Consensus engine (deterministic)

Given a `community_validation` instance with N attestations:

```
attest_count    = number of attestations with verdict="attest"
dissent_count   = number of attestations with verdict="dissent"
abstain_count   = number of attestations with verdict="abstain"
weight(r)       = role weight (data-driven; see definition)
weighted_attest = Σ weight(r) over attesting actors
weighted_dissent= Σ weight(r) over dissenting actors

consensus_score = weighted_attest / (weighted_attest + weighted_dissent)
                  if (weighted_attest + weighted_dissent) > 0
                  else 0.0
```

Role weights are content (frozen JSON), not code. Default weights
(per `community_validation.v1.json`):

| Role | Weight |
| --- | --- |
| `traditional_authority` | 0.30 |
| `village_elder` | 0.20 |
| `community_representative` | 0.15 |
| `surveyor` | 0.20 |
| `field_agent` | 0.05 |
| (others) | 0.00 |

Thresholds (also content):

- **ATTESTED** if `consensus_score ≥ 0.70` AND at least 2 distinct
  roles attest.
- **REJECTED** if `consensus_score ≤ 0.30` OR explicit dissent from
  any `traditional_authority`.
- Otherwise → `ESCALATED` to compliance.

**The score is computed as a pure function of the attestation
event log. Replay reproduces it byte-for-byte.** No ML / LLM.

### 2.4 Attestation rules

Every attestation:

- carries an `Evidence` item (audio/video/signature/written) via
  the Consent pipeline (ADR-0020) — a `community_witness_attestation`
  Evidence kind.
- includes a structured verdict (`attest` / `dissent` / `abstain`).
- includes the actor's signature + the timestamp.
- is **append-only**. A subsequent contradictory attestation by the
  same actor produces a "revised attestation" event — but the
  original is preserved in the chain.

A community member who has not been authenticated as a recognised
role MAY observe but MAY NOT attest. PEP rejects.

### 2.5 Clarification loops

If a witness raises ambiguity ("this beacon is unclear"), they file
a `clarification.v1` request. The instance pauses; the requester is
named; the addressed party has a timer (default 14 days) to respond.

Response options:
- `clarify` — additional Evidence is attached.
- `withdraw` — the original attestation is withdrawn (recorded as
  such; not deleted).
- `escalate` — sends the whole community_validation instance to
  compliance_review.

### 2.6 Rejection paths

- **Implicit rejection**: consensus score below threshold ⇒
  `REJECTED` terminal state.
- **Explicit dissent**: any `traditional_authority` dissents ⇒
  immediate `REJECTED`.
- **Compliance rejection**: `compliance_review` returns
  `REJECTED` ⇒ workflow terminates.
- **SG rejection**: `surveyor_general_review` returns `REJECTED` ⇒
  workflow terminates and Registry is never committed.

Every rejection is recorded, never hidden. The aggrieved party MAY
file an `attestation_appeal.v1`.

### 2.7 Escalation

A workflow is **escalated** when:
- consensus is inconclusive,
- the clarification timer fires without response,
- the surveyor encounters an irreconcilable boundary dispute,
- a `compliance_officer` invokes their pause-and-escalate authority.

Escalation transitions the instance into the next reviewer's queue.
The reviewer's verdict transitions the instance back, forward, or
terminal.

### 2.8 Evidence requirements (binding)

| Event | Required Evidence |
| --- | --- |
| `community_validation.attestation_recorded` | one consent-grade Evidence item per attestation |
| `survey_assignment.report_submitted` | one Evidence item containing the surveyor's report (signed) |
| `compliance_review.approved` | a compliance memo as an Evidence item |
| `surveyor_general_review.approved` | the SG's signed approval as an Evidence item |
| `attestation_appeal.decision_final` | the appeal decision as an Evidence item |

The workflow MUST NOT advance past any of those states without the
declared Evidence id present in the event payload.

### 2.9 Deterministic consensus scoring (constitutional rule)

The consensus formula is published in
`workflow_definitions/community_validation.v1.json` and frozen.
Changes require `community_validation.v2`. Every recomputation
matches every prior computation byte-for-byte.

### 2.10 Replay

Per ADR-0019 §2.8. Replay of any community_validation instance
re-derives:
- attestation set (membership + ordering),
- clarification loops in original order,
- consensus score,
- terminal verdict.

`test_community_validation_replay_byte_identical` is a binding
Phase 4 acceptance test.

### 2.11 Audit

Every command on every workflow emits a structured event AND a
row to the kernel audit log. Append-only. No deletions, ever.
A final terminal state of any instance is itself a permanent record
of the community's verdict and the reasons.

## 3. Constitutional constraints

| # | Rule | Notes |
| --- | --- | --- |
| C-21.1 | The Surveyor General is the ONLY role that may emit `registry.command.commit_parcel`. | PEP-enforced. |
| C-21.2 | Every attestation MUST be Evidence-backed. | C-19.1 transitive. |
| C-21.3 | Consensus score is pure-functional and deterministic. | No ML / LLM. |
| C-21.4 | Rejected workflows leave a complete, queryable rejection record. | Append-only. |
| C-21.5 | Appeals are themselves workflows; appeals never modify the original instance's events. | A new `attestation_appeal.v1` instance is spawned. |
| C-21.6 | No role may attest on behalf of another. | One actor = one attestation. |
| C-21.7 | Re-attestations are revisions, not overwrites. | Original event preserved. |

## 4. Consequences

### Positive

- Recognises the social reality of land governance — communities
  decide, registrars record.
- Deterministic consensus is defensible in court (the formula is
  published and auditable).
- The Surveyor General gate prevents premature Registry commits.

### Negative / trade-offs

- A claim's path to the Registry is longer; UX must communicate
  progress and SLAs clearly.
- Role weights are politically sensitive; freezing them publicly
  is necessary even if uncomfortable.

## 5. Alternatives considered

| Alternative | Why rejected |
| --- | --- |
| **Simple majority-vote consensus** | Treats role weights as equal; ignores the social reality of traditional authorities' standing. |
| **Manual operator-driven validation** | Loses replay determinism; opaque to citizens. |
| **AI-assisted consensus** | Violates C-19.8 (no AI decision-making). |

## 6. Open questions

- Jurisdiction-specific role weight overrides (per-state JSON
  overlays of `community_validation.v1.json`). Resolution:
  Workflow Definition allows a `jurisdiction_overlays` map; default
  weights apply if no overlay exists.
- Appeal-of-appeal: the appeal workflow may itself be appealed to a
  court. Court orders enter the system as Evidence items and
  trigger `inheritance.customary_resolution` (ADR-0022) or a fresh
  community workflow instance.

---

> ADR-0021 declares the **what** of community validation. The
> **how** is enumerated in `PHASE4_BLUEPRINT.md §5`.
