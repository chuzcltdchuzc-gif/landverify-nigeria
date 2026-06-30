# Phase 4 — Consolidated State Machine Catalogue

> **Status:** DRAFT — part of the Phase 4 Blueprint Package.
> **Scope:** every state machine in Phase 4, in one document.
> **Authority:** ADR-0019 / 0020 / 0021 / 0022.
> **Discipline:** any transition not listed is **illegal** and raises `InvariantViolation`.

This catalogue exists so an Operator reviewing the Blueprint Package
can survey every state graph without spelunking through four ADRs.
It is **derived content** — the binding source for each graph is the
ADR cited inline.

---

## 1. Conventions

- **States** in `CAPS`.
- **Terminal states** marked `(T)`.
- **Required role(s)** for the transition appear in `[brackets]`.
- **Emitted event** appears after `→`.
- **Outbound command** (cross-context) appears after `⇒`.
- **Timer** appears after `⏲`.

A state machine is **valid** only if:
- Every non-terminal state has at least one outbound transition.
- Every terminal state is reachable from the initial state.
- No cycle exists without a guard.
- No outbound command is emitted from outside `application/`.

The engine validates these conditions at definition load time.
Invalid definitions refuse to load (RB-5 in `PHASE4_BLUEPRINT §9`).

---

## 2. `consent.v1` (ADR-0020 §2.2)

```
REQUESTED ──[field_agent | compliance_officer]──▶ IN_WITNESS
   │
   ├──[originator]──▶ CANCELLED (T)
   │
   └──⏲ 7 days──▶ EXPIRED (T)

IN_WITNESS ──[witness * required-slate]──▶ CAPTURED
   │
   ├──[principal]──▶ DECLINED (T)
   │
   └──⏲ 14 days──▶ EXPIRED (T)

CAPTURED ──[system]──▶ COMPLETED (T)

COMPLETED ──[principal]──▶ REVOKED (T)
COMPLETED ──[compliance_officer]──▶ INVALIDATED (T)
```

## 3. `consent_revocation.v1` (ADR-0020 §2.7)

```
REVOKE_REQUESTED ──[principal]──▶ REVOKE_CAPTURED
REVOKE_CAPTURED ──[system]──▶ REVOKE_RECORDED (T)
                                  → consent.revoked.v1
```

## 4. `survey_assignment.v1` (ADR-0021 §2.1.1)

```
ASSIGNED ──[surveyor]──▶ ACCEPTED
   │
   ├──[surveyor]──▶ DECLINED (T)
   │
   └──[operator]──▶ REASSIGNED (T) (spawns new instance)

ACCEPTED ──[surveyor]──▶ IN_FIELD
IN_FIELD ──[surveyor]──▶ FIELD_COMPLETE
FIELD_COMPLETE ──[surveyor]──▶ REPORT_PENDING
REPORT_PENDING ──[surveyor]──▶ REPORT_SUBMITTED (T) ⇒ spawn community_validation.v1
   │
   └──⏲ 30 days──▶ ABANDONED (T)
```

## 5. `community_validation.v1` (ADR-0021 §2.1.2)

```
INITIATED ──[system]──▶ ATTESTATION_OPEN

ATTESTATION_OPEN ──[village_elder | traditional_authority |
                     community_representative | surveyor]──▶ (attestation_recorded)
ATTESTATION_OPEN ──[any attesting role]──▶ CLARIFICATION_REQUESTED
ATTESTATION_OPEN ──[system, when slate complete]──▶ ATTESTATION_CLOSED
ATTESTATION_OPEN ──⏲ 21 days──▶ ESCALATED (T)

CLARIFICATION_REQUESTED ──[addressed party]──▶ CLARIFICATION_RESOLVED ──▶ ATTESTATION_OPEN
CLARIFICATION_REQUESTED ──⏲ 14 days──▶ ESCALATED (T)

ATTESTATION_CLOSED ──[system]──▶ CONSENSUS_COMPUTED

CONSENSUS_COMPUTED ──[score ≥ 0.70 & ≥2 roles attest]──▶ ATTESTED (T) ⇒ spawn compliance_review.v1
CONSENSUS_COMPUTED ──[score ≤ 0.30 OR traditional_authority dissent]──▶ REJECTED (T)
CONSENSUS_COMPUTED ──[otherwise]──▶ ESCALATED (T) ⇒ spawn compliance_review.v1
```

## 6. `clarification.v1` (ADR-0021 §2.1.6)

```
REQUESTED ──[system]──▶ RESPONSE_AWAITED
RESPONSE_AWAITED ──[addressed party]──▶ RESPONDED ──▶ CLOSED (T)
RESPONSE_AWAITED ──⏲ 14 days──▶ TIMED_OUT (T)
```

## 7. `compliance_review.v1` (ADR-0021 §2.1.3)

```
QUEUED ──[compliance_officer]──▶ UNDER_REVIEW
UNDER_REVIEW ──[compliance_officer]──▶ APPROVED (T) ⇒ spawn surveyor_general_review.v1
UNDER_REVIEW ──[compliance_officer]──▶ RETURNED (T) ⇒ bounce to community_validation w/ findings
UNDER_REVIEW ──[compliance_officer]──▶ REJECTED (T)
QUEUED       ──⏲ 30 days──▶ ESCALATED (notifies super_admin)
```

## 8. `surveyor_general_review.v1` (ADR-0021 §2.1.4)

```
QUEUED ──[surveyor_general]──▶ UNDER_REVIEW
UNDER_REVIEW ──[surveyor_general]──▶ APPROVED (T) ⇒ registry.command.commit_parcel
UNDER_REVIEW ──[surveyor_general]──▶ HELD_FOR_INFO (T) ⇒ spawn clarification.v1
UNDER_REVIEW ──[surveyor_general]──▶ REJECTED (T)
```

## 9. `attestation_appeal.v1` (ADR-0021 §2.1.5)

```
FILED ──[compliance_officer]──▶ HEARD
HEARD ──[compliance_officer]──▶ DECISION_DRAFTED
HEARD ──[compliance_officer]──▶ DISMISSED (T)
DECISION_DRAFTED ──[compliance_officer]──▶ DECISION_FINAL (T)
```

## 10. `inheritance.v1` (ADR-0022 §2.2)

```
FILED ──[compliance_officer]──▶ DEATH_VERIFICATION
   │
   └──[filer]──▶ WITHDRAWN (T)

DEATH_VERIFICATION ──[compliance_officer with Evidence]──▶ BENEFICIARIES_GATHERED
DEATH_VERIFICATION ──[compliance_officer]──▶ NULLIFIED (T) (death record invalidated)

BENEFICIARIES_GATHERED ──[compliance_officer]──▶ REGIME_DETERMINED

REGIME_DETERMINED ──[system, customary attestations present if required]──▶ SHARES_COMPUTED

SHARES_COMPUTED ──[system]──▶ BENEFICIARY_CONSENTS_COLLECTED ⇒ spawn consent.v1 per beneficiary

BENEFICIARY_CONSENTS_COLLECTED ──[all COMPLETED, single beneficiary]──▶ COMMIT_PENDING
BENEFICIARY_CONSENTS_COLLECTED ──[all COMPLETED, multiple]──▶ SUBDIVISION_DRAFTED
BENEFICIARY_CONSENTS_COLLECTED ──[any dispute]──▶ DISPUTED

SUBDIVISION_DRAFTED ──[surveyor]──▶ COMMUNITY_REVIEW ⇒ spawn community_validation.v1
COMMUNITY_REVIEW ──[ATTESTED]──▶ SG_REVIEW ⇒ spawn surveyor_general_review.v1
SG_REVIEW ──[APPROVED]──▶ COMMIT_PENDING
COMMIT_PENDING ──[system]──▶ COMMITTED (T) ⇒ registry.command.{create_parcel | transfer_ownership | supersede_parcel}

DISPUTED ──[aggrieved party]──▶ APPEAL_FILED ⇒ spawn inheritance_appeal.v1
APPEAL_FILED ──[appeal resolved]──▶ (return to SHARES_COMPUTED or REGIME_DETERMINED per appeal verdict)
DISPUTED ──[compliance_officer]──▶ CLOSED_UNRESOLVED (T)
```

## 11. `inheritance_appeal.v1` (ADR-0022 §2.12)

```
FILED ──[compliance_officer]──▶ NOTICED
NOTICED ──[compliance_officer]──▶ HEARD
HEARD ──[compliance_officer]──▶ DECISION_DRAFTED
HEARD ──[compliance_officer]──▶ DISMISSED (T)
DECISION_DRAFTED ──[compliance_officer]──▶ DECISION_FINAL (T)
   verdicts: {uphold, revise_shares, revise_regime, nullify}
```

## 12. `subdivision.v1` (ADR-0022 §2.10)

```
DRAFTED ──[surveyor]──▶ COMMUNITY_REVIEW ⇒ spawn community_validation.v1
COMMUNITY_REVIEW ──[ATTESTED]──▶ SG_REVIEW ⇒ spawn surveyor_general_review.v1
SG_REVIEW ──[APPROVED]──▶ APPROVED (T)
SG_REVIEW ──[REJECTED]──▶ REVISION_REQUESTED ──▶ DRAFTED
```

## 13. `notification.v1` (PHASE4_SPEC §3.4)

```
QUEUED ──[system]──▶ DISPATCHED
DISPATCHED ──[adapter ack]──▶ DELIVERED (T)
DISPATCHED ──[adapter nack]──▶ FAILED (T)  (no retry — notifications are best-effort)
QUEUED ──⏲ 24h──▶ EXPIRED (T)
```

## 14. Engine-level helpers (ADR-0019 §2.3 / 2.9)

### 14.1 `withdrawal.v1`

```
REQUESTED ──[originator]──▶ APPROVED (T) (cancels parent instance)
REQUESTED ──[compliance_officer]──▶ DENIED (T)
```

### 14.2 `suspension.v1` (super_admin only)

```
ACTIVE ──[super_admin]──▶ SUSPENDED (T)  (with reason + audit_log row)
```

### 14.3 `reactivation.v1` (super_admin only)

```
SUSPENDED ──[super_admin]──▶ ACTIVE (T)  (with reason + audit_log row)
```

### 14.4 `cancellation.v1`

```
ACTIVE ──[originator | super_admin]──▶ CANCELLED (T)
```

### 14.5 `escalation.v1` (helper, engine-emitted)

```
TRIGGERED ──[engine timer]──▶ ROUTED  (to declared escalation queue)
ROUTED ──[reviewer]──▶ RESOLVED (T)
```

---

## 15. Cycle / reachability matrix (engine-validated at load)

| Workflow | Initial | Terminals | Cycles? |
| --- | --- | --- | --- |
| consent.v1 | REQUESTED | COMPLETED, DECLINED, EXPIRED, CANCELLED, INVALIDATED, REVOKED | none |
| consent_revocation.v1 | REVOKE_REQUESTED | REVOKE_RECORDED | none |
| survey_assignment.v1 | ASSIGNED | REPORT_SUBMITTED, DECLINED, REASSIGNED, ABANDONED | none |
| community_validation.v1 | INITIATED | ATTESTED, REJECTED, ESCALATED | ATTESTATION_OPEN ↔ CLARIFICATION_REQUESTED (guarded by clarification.v1 closure) |
| clarification.v1 | REQUESTED | CLOSED, TIMED_OUT | none |
| compliance_review.v1 | QUEUED | APPROVED, RETURNED, REJECTED | none |
| surveyor_general_review.v1 | QUEUED | APPROVED, HELD_FOR_INFO, REJECTED | none |
| attestation_appeal.v1 | FILED | DECISION_FINAL, DISMISSED | none |
| inheritance.v1 | FILED | COMMITTED, NULLIFIED, WITHDRAWN, CLOSED_UNRESOLVED | DISPUTED → SHARES_COMPUTED via APPEAL_FILED (guarded) |
| inheritance_appeal.v1 | FILED | DECISION_FINAL, DISMISSED | none |
| subdivision.v1 | DRAFTED | APPROVED | DRAFTED ↔ REVISION_REQUESTED (guarded by SG review) |
| notification.v1 | QUEUED | DELIVERED, FAILED, EXPIRED | none |
| withdrawal.v1 | REQUESTED | APPROVED, DENIED | none |
| suspension.v1 | ACTIVE | SUSPENDED | none |
| reactivation.v1 | SUSPENDED | ACTIVE | none |
| cancellation.v1 | ACTIVE | CANCELLED | none |
| escalation.v1 | TRIGGERED | RESOLVED | none |

Every cycle in the table is guarded by an external workflow's
terminal — none are unbounded.

---

## 16. Cross-references

| Workflow | ADR | PHASE4_SPEC reference |
| --- | --- | --- |
| consent.v1 / consent_revocation.v1 | ADR-0020 | §3.2 invariants, §6 PEP |
| survey_assignment.v1 → SG | ADR-0021 | §3.3 invariants, §6 PEP |
| inheritance.v1 / subdivision.v1 / inheritance_appeal.v1 | ADR-0022 | §3.4 invariants, §6 PEP |
| engine helpers | ADR-0019 | §3.1 invariants |

This catalogue is **derived**; the ADRs are the binding source. Any
discrepancy must be resolved by amending the relevant ADR first,
then regenerating this document.
