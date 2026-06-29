"""Append-only chain helper for Phase 3.6 immutable logs.

Used by:
* ``EvidenceIntegrityCheck`` (Phase 3.6) — per-evidence chained log.
* ``AnchorAttempt`` (Phase 3.6) — per-batch chained attempt log.

Chain contract:
    seq_0:   prev_hash = None        entry_hash = sha256(canonical_json(payload_0))
    seq_n:   prev_hash = entry_n-1   entry_hash = sha256(prev_hash || canonical_json(payload_n))

The repository layer enforces append-only at the adapter level; this
module owns the cryptographic primitive only. Pure stdlib.
"""
from __future__ import annotations

import hashlib
import json
from typing import Optional


def canonical_payload_bytes(payload: dict) -> bytes:
    """Deterministic JSON encoding for chain hashing."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=False).encode("utf-8")


def compute_entry_hash(prev_hash: Optional[str], payload: dict) -> str:
    """Compute the entry_hash for the next chain link.

    * ``prev_hash`` is ``None`` for the genesis entry.
    * The encoding ``prev_hash || canonical_json(payload)`` matches the
      Phase 3.4 ``compute_merkle_root`` primitive (ASCII concatenation
      of hex digests, then sha256). Verifiers reproduce this exactly.
    """
    h = hashlib.sha256()
    if prev_hash is not None:
        if not isinstance(prev_hash, str) or len(prev_hash) != 64:
            raise ValueError(f"invalid prev_hash: {prev_hash!r}")
        h.update(prev_hash.encode("ascii"))
    h.update(canonical_payload_bytes(payload))
    return h.hexdigest()


def verify_chain(entries: list[dict], *, prev_hash_field: str = "prev_hash",
                  entry_hash_field: str = "entry_hash",
                  seq_field: str = "seq",
                  payload_fields: Optional[list[str]] = None) -> bool:
    """Verify a list of chain entries in ``seq`` order.

    Each entry must carry ``prev_hash``, ``entry_hash``, ``seq``, and
    the payload fields participating in the chain. Returns ``True`` iff
    every entry's ``entry_hash`` is reproducible from its ``prev_hash``
    and payload, AND ``prev_hash`` matches the previous entry's
    ``entry_hash``.
    """
    if not entries:
        return True
    sorted_entries = sorted(entries, key=lambda e: e[seq_field])
    prev: Optional[str] = None
    for idx, entry in enumerate(sorted_entries):
        if entry.get(prev_hash_field) != prev:
            return False
        payload = ({k: entry[k] for k in payload_fields}
                    if payload_fields else
                    {k: v for k, v in entry.items()
                     if k not in (prev_hash_field, entry_hash_field)})
        expected = compute_entry_hash(prev, payload)
        if entry[entry_hash_field] != expected:
            return False
        prev = entry[entry_hash_field]
    return True
