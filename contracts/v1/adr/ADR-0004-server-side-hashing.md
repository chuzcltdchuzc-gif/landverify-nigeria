# ADR-0004 — Server-Side Hashing & Verification Discipline (Phase 3, was 016)

* **Status:** Proposed (blocking on Phase 3.0 sign-off)
* **Date:** 2026-06-28
* **Contract version introduced:** `1.2.0`
* **Authors:** Platform team
* **Related:** ADR-0003 (Evidence Context), ADR-0005 (Anchor Saga),
  ADR-0006 (Legal Hold + Remediation)

## Context

Client-supplied content hashes cannot be trusted: a malicious or buggy
client can submit a hash that does not match the bytes it uploaded. If
the platform relied on a client hash for seal eligibility, it would
issue legally-defensible seals over content the platform never
independently verified — fatal to court admissibility.

The Phase 3 directive is explicit:

> Compute/verify evidence hashes server-side; client hashes are claims
> only; an item is not seal-eligible until server-verified.

## Decision

1. **Two-pass server hashing.** Every upload is:
    1. **Streamed-during-write**: as bytes arrive in each multipart part,
       the server feeds them through a running `hashlib.sha256()`. The
       running hash is persisted into the integrity log per part.
    2. **Read-back-and-re-hash**: after `complete_multipart`, the server
       streams the object back **out of storage** (a fresh, independent
       read) and recomputes the SHA-256 from scratch. Only after this
       pass equals the streamed-during-write hash does the item move to
       `verified` and become seal-eligible.
2. **Client hashes are claims.** `client_hash_claim` is recorded on the
   item and written to the integrity log. If it differs from the
   server's verified hash the item is rejected with `409
   evidence.hash_mismatch`; the integrity log records both values and
   the event `evidence.item.hash_mismatch.v1` is emitted.
3. **Seal eligibility.** `Seal.create()` accepts only items whose
   `hash_verified` flag is `true`. The aggregate enforces this; the
   repository's `add()` will reject otherwise.
4. **Algorithm.** SHA-256 (RFC 6234). The field `hash_algorithm` is
   pinned to `"SHA-256"` for v1; bumping it is a contract change.
5. **Streaming hash test vectors.** NIST SHA-256 test vectors are pinned
   into the test suite; the streaming implementation MUST match the
   one-shot reference.
6. **Storage backends do not influence the hash.** The hash is over the
   plaintext bytes the client uploaded, BEFORE envelope encryption (ADR-
   amends Phase 0 ADR on encryption). Decryption-then-rehash is the
   verification path; the storage adapter exposes
   `open_for_streaming_hash(key)` which yields plaintext bytes for this
   purpose.

## Consequences

### Positive

* No "trusted client" assumption anywhere in the hashing pipeline.
* Court export bundles can carry a hash whose provenance is fully
  recorded (claim → streamed → read-back → all three logged with
  timestamps and principals).
* The verify pass also serves as a smoke test of the storage adapter:
  if the read-back fails, we discover storage problems before the item
  is sealed.

### Negative / Trade-offs

* Two passes is more bandwidth than one. Mitigation: the read-back
  stream is intra-region (storage adapter ↔ application service) and
  occurs once per item lifetime; the seal path amortizes the cost.

## Compliance

Phase Acceptance Review must demonstrate:

* A test that submits a deliberately-mismatched `client_hash_claim` and
  asserts the item is rejected with `409 evidence.hash_mismatch` and
  an `evidence.item.hash_mismatch.v1` event in the outbox.
* A test that submits no claim, completes upload, and confirms `Seal.
  create()` succeeds — i.e. claims are optional, server verification is
  mandatory.
* NIST vector tests against the streaming SHA-256 implementation.
