# ADR-0020 — Consent Engine (Phase 4)

* **Status:** DRAFT — pending operator approval
* **Phase:** 4 (Workflows · sub-context)
* **Depends on:** ADR-0019 (Workflow Engine), ADR-0007 (Evidence Aggregate), ADR-0009 (Timeline + Custody)
* **Owns:** the consent workflow sub-context — capturing legally defensible, multi-modal, witnessed consent.

---

## 1. Context

Land-related transactions in the operating jurisdictions require
**provable, witnessed, legally defensible consent** from one or
more identified principals. Examples:

- A spousal co-owner attesting to a sale.
- A village chief witnessing a customary transfer.
- A surveyor's neighbour-adjacency consent ("beacon witness").
- An inheritance beneficiary acknowledging a share allocation.

Today the platform records ad-hoc PDFs and signatures as Evidence
items. That works for storage but does NOT produce a legally
defensible structured artifact: there is no machine-checkable record
of *who said yes, when, how, in front of whom, and with what
revocation rights*.

The Consent Engine fills that gap as a Workflow sub-context.

## 2. Decision

Introduce a dedicated `ConsentRequest` aggregate, capture flow,
strength score, and revocation lifecycle. Every state-bearing
transition is human-signed; every capture artifact is an Evidence
item (Phase 3); every score is deterministic and re-computable from
the event stream.

### 2.1 Aggregates

| Aggregate | Owns |
| --- | --- |
| `ConsentRequest` | the consent intent — purpose, principals, modes required, witness slate, expiry, current state. |
| `ConsentCapture` | a single in-witness recording (audio / video / signature / written attestation) bound to one principal of one `ConsentRequest`. Immutable once recorded. |
| `WitnessAttestation` | an identified witness's positive attestation that they observed a `ConsentCapture`. Immutable. |
| `ConsentRevocation` | terminal revocation event by the original principal. Immutable, recorded but does not retroactively void prior reliance. |

`ConsentRequest` is a Workflow `WorkflowInstance` (ADR-0019 §2.2)
whose `WorkflowDefinition` is `consent.v1`. The other three are
domain aggregates owned by this sub-context.

### 2.2 Consent lifecycle (state machine)

```
                    ┌───── DECLINED (terminal)
                    │
   REQUESTED ──▶ IN_WITNESS ──▶ CAPTURED ──▶ COMPLETED (terminal)
        │             │             │           │
        │             │             │           └─▶ REVOKED (terminal)
        │             │             │                  (with reliance window)
        │             │             └─▶ INVALIDATED (terminal — defect found)
        │             │
        │             └─▶ EXPIRED (terminal — timer fired)
        │
        └─▶ CANCELLED (terminal — requester withdrew before witness)
```

| State | Description | Role-required to transition out |
| --- | --- | --- |
| `REQUESTED` | Created by a Workflow saga or operator. Awaiting witness slate ack. | `field_agent`, `surveyor`, `compliance_officer` |
| `IN_WITNESS` | Witnesses confirmed; capture session open. | the principal (signs); witnesses (attest) |
| `CAPTURED` | All required modes captured + all required witnesses attested. | system (auto-transition) |
| `COMPLETED` | Strength score computed; consent issued an immutable identifier. | terminal |
| `DECLINED` | Principal refused mid-capture. | terminal |
| `EXPIRED` | Timer fired before completion. | terminal |
| `INVALIDATED` | Compliance review found a defect post-completion. | terminal · audit-only by `compliance_officer` |
| `REVOKED` | Principal exercised revocation right. | terminal · principal only |
| `CANCELLED` | Originator withdrew before any witness arrived. | terminal · originator only |

Illegal transitions: any edge not drawn above. The engine raises
`InvariantViolation` on an illegal attempted transition.

### 2.3 Capture modes

| Mode | What it stores | Evidence kind emitted |
| --- | --- | --- |
| `audio` | Voice recording of the principal stating consent verbatim. | `evidence.kind=consent_audio` |
| `video` | Audio + visual capture (preferred for high-stakes). | `evidence.kind=consent_video` |
| `signature` | Wet or digital signature on the structured consent statement. | `evidence.kind=consent_signature` |
| `written_attestation` | A scanned, hand-written attestation. | `evidence.kind=consent_written` |
| `biometric_thumbprint` | A captured thumbprint with liveness metadata. | `evidence.kind=consent_biometric` |

The consent statement TEXT itself is a structured, versioned
template (`consent_statement.v1.json` in `workflow_definitions/`).
Every capture binds to the exact statement version.

### 2.4 Witness handling

A `ConsentRequest` declares the **witness slate**: a list of roles
plus the minimum count per role. Examples:

| Workflow | Required slate |
| --- | --- |
| Spousal co-owner consent | 1 × `compliance_officer` |
| Customary transfer consent | 2 × `traditional_authority` AND 1 × `community_representative` |
| Beacon adjacency consent | 1 × `surveyor` AND 1 × adjacent land owner |
| Inheritance acceptance | 1 × `compliance_officer` |

Each witness must:
1. Authenticate (JWT in possession).
2. Issue `consent.witness.confirm_arrival` (records presence).
3. After `ConsentCapture` is sealed (Evidence WORM applied), issue
   `consent.witness.attest` carrying:
   - their identifier,
   - the capture id they attest to,
   - free-text observation,
   - their signature (digital, separate Evidence item).

Witness attestations are themselves Evidence items —
`evidence.kind=consent_witness_attestation`.

### 2.5 Strength scoring (deterministic, explainable)

Each `ConsentRequest` carries a **strength** score on `COMPLETED`,
computed as a pure function of the captured artifacts:

```
strength = base(mode)
         + 0.15 × min(witness_count, required_count)
         + 0.10 × biometric_present
         + 0.10 × video_present
         + 0.05 × audio_present
         + 0.10 × digital_signature_present
         + 0.05 × statement_template_version_ack
         - 0.20 × any_defect_observed
clamped to [0.0, 1.0]
```

`base(mode)`: `signature`=0.40 · `audio`=0.50 · `video`=0.65 ·
`biometric_thumbprint`=0.55 · `written_attestation`=0.30.

The exact formula lives in `workflow_definitions/consent.v1.json`
under `scoring`. It is **frozen content** — never changed in place.
A new formula requires `consent.v2`.

Scoring is **assistive only**. The score does NOT decide
acceptance — a human compliance officer does. The score exists to
let downstream workflows (community validation, inheritance, etc.)
require minimum strengths (e.g. "inheritance transfers require
consent strength ≥ 0.7").

**No ML / LLM is used in scoring.** This is a constitutional vow
(C-19.8 in ADR-0019).

### 2.6 Legal authority

Consent is legally authoritative when:

1. State is `COMPLETED`,
2. All required witnesses attested,
3. Statement template version matches the version cited in the
   request, AND
4. Strength meets or exceeds the threshold the consuming workflow
   declared.

Anything else is "insufficient" — the consuming workflow MUST
either request additional capture, escalate to compliance, or
abandon the transaction.

### 2.7 Revocation

A principal MAY revoke a `COMPLETED` consent at any time before
the consuming workflow reaches its own terminal state. Revocation
is itself a workflow:

```
REVOKE_REQUESTED ──▶ REVOKE_CAPTURED ──▶ REVOKE_RECORDED (terminal)
```

Revocation produces a `consent.revoked.v1` event. The consuming
workflow observes this event and:
- if it has NOT yet relied on the consent → cancels itself.
- if it HAS relied (e.g. a Registry ownership transfer already
  recorded) → escalates to the appeal workflow (ADR-0021 §rejection
  paths). Past reliance is NEVER undone retroactively; the appeal
  workflow may produce a forward-looking remediation.

Revocations are append-only. A revoked consent is never "un-revoked"
— a new `ConsentRequest` would be required.

### 2.8 Decline handling

If the principal declines DURING capture (state `IN_WITNESS`), the
witness records the decline via `consent.decline.record`. The
request transitions to `DECLINED`. No Evidence item is produced
beyond the witness's attestation that a decline occurred. The
consuming workflow observes `consent.declined.v1` and follows its
declared decline branch.

### 2.9 Evidence linkage (binding rule)

Every `ConsentCapture` MUST result in EXACTLY ONE Evidence item,
sealed and WORM-applied through the Phase 3 pipeline. The
Evidence's `kind` field carries the capture mode (see §2.3). The
Evidence's `payload.consent_capture_id` carries the back-reference.

The consent engine MUST NOT write to the Evidence collections
directly (C-19.1). It emits `evidence.commands.initiate_upload`,
`evidence.commands.complete_upload`, `evidence.commands.seal`, and
`evidence.commands.apply_worm` through the kernel outbox. The
Evidence context's existing command handlers accept or reject.

### 2.10 Audit rules

- Every state transition emits `consent.state_entered.v1`.
- Every witness arrival emits `consent.witness.arrived.v1`.
- Every witness attestation emits `consent.witness.attested.v1`.
- Every revocation emits `consent.revoked.v1`.
- The append-only audit log captures every command emitted, with
  actor, principal, and correlation_id.

### 2.11 Replay behaviour

A `ConsentRequest` is event-sourced; replay rules are inherited
from ADR-0019 §2.8. Replay re-derives:
- current state,
- captured modes set,
- witness attestation set,
- strength score (pure function — must match byte-for-byte).

The "Phase 4 Acceptance Gate" includes a binding test:
`test_consent_replay_byte_identical` — analogous to ADR-0010's
determinism gate.

## 3. Constitutional constraints (binding for Consent)

| # | Rule | Notes |
| --- | --- | --- |
| C-20.1 | Consent never mutates Registry directly. | Registry transfers happen through their own commands once consent is COMPLETED. |
| C-20.2 | Every capture is an immutable Evidence item via the Phase 3 pipeline. | C-19.1 transitive enforcement. |
| C-20.3 | Strength score is deterministic and pure. | No ML / LLM. |
| C-20.4 | Witness attestation requires authenticated identity. | PEP enforcement. |
| C-20.5 | Revocation is append-only; past reliance is never undone. | Domain invariant. |
| C-20.6 | The legal acceptance threshold belongs to the consuming workflow, not to consent itself. | Consent reports strength; the caller decides. |
| C-20.7 | A `ConsentRequest`'s statement template version cannot change after creation. | Domain invariant. |

## 4. Consequences

### Positive

- Legally defensible structured consent artifacts.
- Multi-jurisdiction-friendly: the witness slate is data, not code.
- Deterministic strength score that compliance officers can defend
  in court.

### Negative / trade-offs

- More steps per transaction; UX must be thoughtful.
- Witness slates require advance configuration per workflow.
- Revocation handling is non-trivial — every consuming workflow
  must declare its revocation branch.

## 5. Alternatives considered

| Alternative | Why rejected |
| --- | --- |
| **Unstructured PDF consent** (status quo) | No machine-checkable artifact; no consensus on what constitutes "consent" across jurisdictions. |
| **ML-derived strength score** | Violates C-19.8 (no AI decision-making) and the explainable-scoring principle. |
| **In-line consent state inside Registry** | Couples Registry to a process concern; violates ADR-0003. |

## 6. Open questions for the implementation phase

- Exact statement template lifecycle (e.g. translation governance).
- Whether biometric thumbprint capture is mandatory in jurisdictions
  with low literacy. Deferred to consuming-workflow configuration.
- Offline capture path (rural areas without connectivity). Deferred
  — likely an asynchronous Evidence upload with delayed witness
  attestation.

---

> ADR-0020 declares the **what** of consent. The **how** —
> directory layout, engine wiring, repository ports — is enumerated
> in `PHASE4_BLUEPRINT.md §4`.
