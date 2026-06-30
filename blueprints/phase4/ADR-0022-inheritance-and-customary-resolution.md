# ADR-0022 — Inheritance & Customary Resolution (Phase 4)

* **Status:** DRAFT — pending operator approval
* **Phase:** 4 (Workflows · sub-context)
* **Depends on:** ADR-0019 (Workflow Engine), ADR-0020 (Consent Engine), ADR-0021 (Community Validation)
* **Owns:** the inheritance and subdivision workflow sub-context — death verification, beneficiary validation, share calculation, customary-law hooks, court-order integration, ownership transfer, appeals.

---

## 1. Context

When a registered land owner dies, the platform must:

1. Verify death with legally defensible evidence.
2. Identify the lawful beneficiaries under the applicable legal
   regime (customary, Islamic, civil-statutory, or court-ordered).
3. Calculate the share each beneficiary receives using a
   deterministic, jurisdiction-aware formula.
4. Capture each beneficiary's consent or dissent.
5. Subdivide the parcel (creating sub-parcels in Registry) where
   the inheritance produces multiple distinct holdings.
6. Transfer ownership.
7. Provide an explicit appeal path for any aggrieved party.

This is the most legally and socially sensitive workflow in the
platform. Customary law varies by community, statutory law varies
by jurisdiction, and courts may override either. The platform's job
is to **honestly record** the process, not to **decide** the
outcome.

## 2. Decision

Introduce a dedicated `inheritance.v1` workflow plus a small set of
supporting aggregates. Every step is human-authoritative; every
share-calculation rule is published JSON content; every transfer
runs through the existing Registry command bus.

### 2.1 Aggregates

| Aggregate | Owns |
| --- | --- |
| `InheritanceCase` | a single inheritance for one deceased owner — case_id, deceased_owner_id, parcel_ids, applicable_regime, current state. |
| `BeneficiaryClaim` | one identified beneficiary's claim against the case. Holds relationship, share fraction, consent state, supporting Evidence. |
| `ShareCalculation` | the deterministic computation result. Versioned by formula id. |
| `SubdivisionPlan` | the proposed split of parent parcel(s) into sub-parcels per the share calculation. |
| `CourtOrder` | a wrapper for court-ordered overrides — references an Evidence item. |
| `InheritanceAppeal` | a child workflow filed by an aggrieved party. |

### 2.2 Inheritance lifecycle

```
FILED
   ▼
DEATH_VERIFICATION ──▶ BENEFICIARIES_GATHERED ──▶ REGIME_DETERMINED ──▶ SHARES_COMPUTED
                                                                            │
                                                                            ▼
                                                            BENEFICIARY_CONSENTS_COLLECTED
                                                                            │
                          ┌─────────────────────────────────────────────────┤
                          ▼                                                 ▼
                   SUBDIVISION_DRAFTED                                  DISPUTED
                          │                                                 │
                          ▼                                                 ▼
                   COMMUNITY_REVIEW (community_validation.v1 spawned)  APPEAL_FILED
                          │                                                 │
                          ▼                                                 ▼
                  SG_REVIEW (surveyor_general_review.v1 spawned)      APPEAL_RESOLVED
                          │                                                 │
                          ▼                                                 │
                  COMMIT_PENDING                                            │
                          │                                                 │
                          ▼                                                 ▼
                  COMMITTED (terminal — registry transfers emitted)   CLOSED_UNRESOLVED (terminal — frozen pending external action)

WITHDRAWN (terminal — filer withdrew before death verification)
NULLIFIED (terminal — death record invalidated, no transfer occurred)
```

Illegal transitions raise `InvariantViolation`. The full state
table is in `PHASE4_SPEC.md §4`.

### 2.3 Death verification

`DEATH_VERIFICATION` requires:

- One civil death certificate as an Evidence item
  (`kind=death_certificate`),
- OR two `traditional_authority` attestations under the
  Community Validation primitives (ADR-0021) if no civil certificate
  is available in the jurisdiction,
- OR a court order declaring death (e.g. presumption of death after
  prolonged absence).

The verifying actor MUST be a `compliance_officer` who records the
verification verdict with reasoning.

A defect found later in the death record (e.g. the deceased turns
out to be alive) transitions the instance to `NULLIFIED`. Any
ownership transfer already emitted is **NOT undone retroactively**;
instead a fresh `correction_workflow` is initiated by the operator —
the original record stands as historical truth.

### 2.4 Beneficiary validation

Gathering beneficiaries is a multi-step process per jurisdiction.
Each beneficiary is captured as a `BeneficiaryClaim`:

- Identifier (national id, customary name, or court-issued tag).
- Relationship to deceased (`spouse`, `child`, `grandchild`,
  `parent`, `sibling`, `customary_heir`, `court_appointed`).
- Supporting Evidence (birth certificate, marriage certificate,
  customary attestation, court order).
- Consent state (begins `PENDING`).

Beneficiary identification can be challenged. Any aggrieved party
may file a `community_validation.v1` instance against a
`BeneficiaryClaim`. The case pauses until the validation resolves.

### 2.5 Applicable regime determination

The case carries an `applicable_regime` selected from the published
content set:

| Regime | Source | Customary hook |
| --- | --- | --- |
| `statutory_NG_LRA_2004` | Land Use Act 1978 + state laws | none |
| `customary_yoruba_idi_igi` | Yoruba primogeniture-by-mother | per-village override allowed |
| `customary_igbo_okpara` | Igbo primogeniture | per-village override allowed |
| `customary_hausa_islamic` | Maliki Islamic inheritance | computed via Faraidh table |
| `civil_court_order` | a court directly issues shares | uses CourtOrder aggregate |

Selection is made by a `compliance_officer` based on the
deceased's domicile, the parcel's location, and the family's
declared regime. Selection MAY be contested via appeal.

### 2.6 Share calculations (deterministic, content-driven)

Every regime is encoded as a pure function in published JSON content
under `workflow_definitions/inheritance_regimes/`. Examples:

- **Maliki Faraidh table**: structured share fractions (1/2, 1/4,
  1/6, 1/8, …) computed from the beneficiary set.
- **Yoruba *idi-igi***: equal division across uterine groups.
- **Statutory NG default**: spouse 1/3, children equal split of
  2/3, parents only if no descendants.

The calculation:

1. Reads the gathered `BeneficiaryClaim` set.
2. Applies the regime's pure function.
3. Produces a `ShareCalculation` document recording the formula id,
   inputs, and per-beneficiary fractions.
4. Stores the result in the event stream — replay reproduces it
   byte-for-byte.

**No ML / LLM in share calculation.** Constitutional vow C-19.8.

If the regime's pure function cannot produce a deterministic split
(e.g. ambiguous beneficiary set), the case transitions to
`DISPUTED`, and a `community_validation.v1` or court order is
required to disambiguate.

### 2.7 Beneficiary consent

Each `BeneficiaryClaim` collects its own `ConsentRequest`
(ADR-0020):

- `purpose`: "Acknowledge share of <fraction> in parcel(s) <ids> per
  <regime_id>".
- `witness_slate`: 1 × `compliance_officer` + 1 ×
  `traditional_authority` (default; jurisdiction overlays may
  override).
- `strength_required`: 0.7.

A beneficiary may:
- `accept`: consent COMPLETED, claim status `ACCEPTED`.
- `decline`: claim status `DECLINED`. Their share is redistributed
  per the regime's "decline" rule.
- `dispute`: spawns `community_validation` for that claim. Case
  transitions to `DISPUTED` if multiple disputes accumulate.

### 2.8 Customary law hooks

A `customary_*` regime MAY declare a list of village-elder roles
whose attestation is REQUIRED before share computation. The
case cannot exit `REGIME_DETERMINED` until those attestations are
captured (ADR-0021 primitives).

Customary overrides are content-driven JSON, never code, so a new
jurisdiction is onboarded by publishing a new overlay.

### 2.9 Court order integration

A `CourtOrder` is captured as a typed Evidence item
(`kind=court_order`) plus a structured wrapper:

```jsonc
{
  "court_order_id": "co_...",
  "court_reference": "FHC/L/2026/...",
  "issuing_court": "Federal High Court, Lagos",
  "evidence_id": "evi_...",
  "directives": [
    { "verb": "appoint_administrator", "party_id": "..." },
    { "verb": "set_share", "beneficiary": "...", "fraction": "1/3" },
    { "verb": "override_regime", "regime_id": "civil_court_order" }
  ],
  "issued_at": "2026-...",
  "received_at": "2026-..."
}
```

Directives carry **explicit machine-readable verbs** (an enumerated
set, frozen as content). Free-text directives require a
`compliance_officer` to translate into the enumerated set before the
order takes effect.

A court order can:
- override the regime,
- set explicit shares,
- halt the workflow (`HOLD`),
- order an appeal heard,
- reverse a prior consent (with explicit reliance-window handling
  per ADR-0020 §2.7).

A court order is itself an Evidence item subject to WORM —
unforgeable after sealing.

### 2.10 Subdivision rules

If the share calculation produces multiple distinct holdings, the
case enters `SUBDIVISION_DRAFTED`. A surveyor produces a
`SubdivisionPlan` — itself an Evidence item with structured geometry.
Community validation reviews it; SG approves it; only THEN the
case emits the Registry commands that:

1. Create N new parcels (one per beneficiary's holding).
2. Transfer ownership of each to the corresponding beneficiary.
3. Mark the parent parcel `SUPERSEDED_BY_SUBDIVISION` (Registry
   supersession semantics from ADR-0009 §9.3 — never hidden).

The Registry context's command handlers accept or reject each;
rejection bounces the case back to `SUBDIVISION_DRAFTED` with the
rejection reason.

### 2.11 Ownership transfer

For a single-beneficiary outcome (no subdivision), the case
emits a single `registry.command.transfer_ownership` referencing
the original parcel. The Registry handler verifies:
- consent COMPLETED with strength ≥ 0.7,
- community_validation ATTESTED,
- surveyor_general_review APPROVED,
- no legal hold active on any linked Evidence,

and records the transfer as an ownership event.

### 2.12 Appeal workflow

`InheritanceAppeal` is a peer instance spawned by an aggrieved
party. It blocks the inheritance case at its current state until
the appeal terminates. The appeal has its own state machine:

```
FILED ──▶ NOTICED ──▶ HEARD ──▶ DECISION_DRAFTED ──▶ DECISION_FINAL (terminal)
                       │
                       └─▶ DISMISSED (terminal)
```

A `DECISION_FINAL` carries one of:
- `uphold` → original inheritance proceeds.
- `revise_shares` → re-run share calculation with new inputs.
- `revise_regime` → return case to `REGIME_DETERMINED`.
- `nullify` → terminate the case as `CLOSED_UNRESOLVED`.

Appeals can themselves be appealed externally — the platform records
the external court order via `CourtOrder` (§2.9).

### 2.13 Supersession

When a parent parcel is subdivided, Registry's existing supersession
chain (ADR-0009 §9.3) records the link from parent → children. The
parent is NEVER deleted. Querying the supersession chain returns
the full inheritance history.

### 2.14 Registry interaction

The inheritance workflow communicates with Registry ONLY through
commands via the kernel outbox. Registry command vocabulary
(Phase 4 additions enumerated in `PHASE4_SPEC.md §6`):

| Command | Outcome |
| --- | --- |
| `registry.command.create_parcel` | new sub-parcel (from subdivision) |
| `registry.command.transfer_ownership` | ownership change |
| `registry.command.supersede_parcel` | parent → child link |

### 2.15 Evidence requirements

Every legally consequential transition is Evidence-backed:

| Event | Evidence kind |
| --- | --- |
| `inheritance.death_verified` | `death_certificate` OR community attestations OR court order |
| `inheritance.beneficiary_validated` | birth/marriage/customary attestation |
| `inheritance.regime_determined` | compliance memo |
| `inheritance.shares_computed` | calculation document (auto-generated) |
| `inheritance.subdivision_drafted` | surveyor's plan |
| `inheritance.committed` | SG approval memo |
| `inheritance.appeal_final` | appeal decision |
| `court_order.received` | court_order |

### 2.16 Replay

Inheritance instances are event-sourced; replay reproduces the
state, beneficiary set, regime selection, share calculation
result, consent set, subdivision plan, and final terminal state
byte-for-byte. `test_inheritance_replay_byte_identical` is a
binding Phase 4 acceptance test.

### 2.17 Audit

Every transition emits an audit_log row + an event. The case's full
history — including dissent, appeals, and nullifications — is
permanently queryable. A case that ends `CLOSED_UNRESOLVED` is a
record of unresolved dispute, not a deletion.

## 3. Constitutional constraints

| # | Rule | Notes |
| --- | --- | --- |
| C-22.1 | Inheritance never writes to Registry; emits commands only. | PEP + outbox. |
| C-22.2 | Share calculation is deterministic and content-driven. | No ML. |
| C-22.3 | Customary overrides are content, not code. | One JSON file per overlay. |
| C-22.4 | Court orders are typed Evidence with enumerated directive verbs. | Free text requires compliance translation. |
| C-22.5 | The Surveyor General is the only role that may emit `commit_parcel`. | Mirrors C-21.1. |
| C-22.6 | Subdivisions supersede; they never delete. | ADR-0009 §9.3. |
| C-22.7 | A nullified case retains its history. | Append-only. |
| C-22.8 | Re-running a calculation must produce the same shares from the same inputs. | Determinism. |

## 4. Consequences

### Positive

- Recognises multiple legal regimes without privileging any.
- Court orders integrate cleanly without breaking the event model.
- Subdivisions are auditable end-to-end.

### Negative / trade-offs

- The workflow is long and human-intensive — by design.
- Customary regime overlays are sensitive content; their
  publication needs an operator approval workflow that itself
  may need to be a Phase 5 concern.

## 5. Alternatives considered

| Alternative | Why rejected |
| --- | --- |
| **Single statutory regime everywhere** | Ignores the lived legal reality of Nigeria, Kenya, Ghana. |
| **AI-derived share calculation** | Violates C-19.8 and the explainability rule. |
| **Direct Registry write for transfer** | Violates C-19.1 / C-22.1. |

## 6. Open questions

- Onboarding workflow for new customary overlays (Phase 5+ concern).
- Integration with national civil registries (death + birth) — a
  per-jurisdiction adapter is the likely shape.
- Handling of cross-border inheritance — explicit scope-out for
  Phase 4.

---

> ADR-0022 declares the **what**. The **how** is in
> `PHASE4_BLUEPRINT.md §6`.
