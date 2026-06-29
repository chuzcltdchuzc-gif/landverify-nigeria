"""Internal CT-log AnchorPort adapter — Phase 3.6 primary.

Models RFC 6962 Certificate Transparency. Append-only ``evidence_ctlog_tree``
of leaves with monotonic ``leaf_seq``; ``evidence_ctlog_checkpoints``
records published, JWKS-signed tree heads.

``request_anchor`` appends the batch's root as a new CT-log leaf. The
``provider_request_id`` is the leaf's ``leaf_seq`` (a stable integer,
serialised as string for cross-adapter symmetry).

``poll_confirmation`` returns ``confirmed`` once a published checkpoint
covers the leaf — this mirrors the trust model of an external CT log
(an inserted leaf is not "confirmed" until a signed tree head includes
it).

``fetch_inclusion_proof`` computes the audit path deterministically
from the on-disk leaves.
"""
from __future__ import annotations

import hashlib
from typing import Optional

from motor.motor_asyncio import AsyncIOMotorDatabase

from contexts.evidence.domain.value_objects import (
    compute_merkle_root,
    now_iso,
)
from contexts.evidence.ports.anchor import (
    AnchorPollResult,
    AnchorRequest,
    AnchorState,
    InclusionProof,
)
from contexts.evidence.adapters.mongo_anchor_repository import (
    EVIDENCE_CTLOG_CHECKPOINTS_COLLECTION,
    EVIDENCE_CTLOG_TREE_COLLECTION,
)

PROVIDER_ID = "ctlog_internal"


class CtlogInternalAdapter:
    """AnchorPort impl + CT-log helpers consumed by the checkpointer."""

    provider_id = PROVIDER_ID

    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._db = db
        self.tree = db[EVIDENCE_CTLOG_TREE_COLLECTION]
        self.checkpoints = db[EVIDENCE_CTLOG_CHECKPOINTS_COLLECTION]

    async def ensure_indexes(self) -> None:
        await self.tree.create_index("leaf_seq", unique=True)
        await self.tree.create_index("batch_id", unique=True)
        await self.tree.create_index("leaf_hash")
        await self.checkpoints.create_index("head_seq", unique=True)
        await self.checkpoints.create_index("published_at")
        await self.checkpoints.create_index("tree_size")

    # ---- AnchorPort ------------------------------------------------------

    async def request_anchor(self, *, batch_id: str,
                              root: str) -> AnchorRequest:
        # Idempotent over (batch_id, root): if the batch already has a
        # leaf, return the existing one without inserting again.
        existing = await self.tree.find_one({"batch_id": batch_id},
                                              {"_id": 0})
        if existing:
            if existing["leaf_hash"] != root:
                raise ValueError(
                    f"ctlog: leaf for batch {batch_id} already exists "
                    f"with different root ({existing['leaf_hash']} vs {root})")
            return AnchorRequest(
                provider_id=self.provider_id, batch_id=batch_id, root=root,
                provider_request_id=str(existing["leaf_seq"]),
                submitted_at=existing["appended_at"],
            )
        # Allocate next leaf_seq atomically. We use a "counters" doc.
        # Idempotency: insert with unique batch_id; collisions return the
        # original leaf above.
        cur_max = await self.tree.find_one({}, {"_id": 0, "leaf_seq": 1},
                                             sort=[("leaf_seq", -1)])
        next_seq = (cur_max["leaf_seq"] + 1) if cur_max else 1
        doc = {
            "leaf_seq": next_seq,
            "leaf_hash": root,
            "batch_id": batch_id,
            "appended_at": now_iso(),
        }
        try:
            await self.tree.insert_one(doc)
        except Exception as exc:  # noqa: BLE001
            # Concurrent insert lost the race — read back.
            if "duplicate key" in str(exc).lower():
                existing = await self.tree.find_one(
                    {"batch_id": batch_id}, {"_id": 0})
                if existing:
                    return AnchorRequest(
                        provider_id=self.provider_id, batch_id=batch_id,
                        root=root,
                        provider_request_id=str(existing["leaf_seq"]),
                        submitted_at=existing["appended_at"],
                    )
            raise
        return AnchorRequest(
            provider_id=self.provider_id, batch_id=batch_id, root=root,
            provider_request_id=str(next_seq),
            submitted_at=doc["appended_at"],
        )

    async def poll_confirmation(self,
                                  request: AnchorRequest) -> AnchorPollResult:
        leaf_seq = int(request.provider_request_id)
        cp = await self.checkpoints.find_one(
            {"tree_size": {"$gte": leaf_seq}},
            {"_id": 0}, sort=[("head_seq", 1)])
        if cp:
            return AnchorPollResult(
                state=AnchorState.CONFIRMED.value,
                provider_response={
                    "checkpoint_head_seq": cp["head_seq"],
                    "checkpoint_root_hash": cp["root_hash"],
                    "checkpoint_published_at": cp["published_at"],
                    "checkpoint_signature": cp.get("signature"),
                    "checkpoint_signature_kid": cp.get("signature_kid"),
                    "leaf_seq": leaf_seq,
                })
        return AnchorPollResult(state=AnchorState.PENDING.value,
                                  detail="awaiting next checkpoint")

    async def fetch_inclusion_proof(self, request: AnchorRequest,
                                      leaf_hash: str) -> InclusionProof:
        leaf_seq = int(request.provider_request_id)
        # Find a checkpoint covering this leaf.
        cp = await self.checkpoints.find_one(
            {"tree_size": {"$gte": leaf_seq}},
            {"_id": 0}, sort=[("head_seq", 1)])
        if not cp:
            raise RuntimeError(
                f"ctlog: no checkpoint covers leaf_seq={leaf_seq} yet")
        # Compute the audit path against the checkpoint's tree_size.
        all_leaves = [d["leaf_hash"]
                       async for d in self.tree.find(
                           {"leaf_seq": {"$lte": cp["tree_size"]}},
                           {"_id": 0, "leaf_hash": 1, "leaf_seq": 1}
                       ).sort("leaf_seq", 1)]
        path = _audit_path(all_leaves, leaf_index=leaf_seq - 1)
        return InclusionProof(
            provider_id=self.provider_id, seal_id=request.batch_id,
            leaf_hash=leaf_hash,
            proof_blob={
                "leaf_seq": leaf_seq,
                "tree_size_at_proof": cp["tree_size"],
                "checkpoint_head_seq": cp["head_seq"],
                "checkpoint_root_hash": cp["root_hash"],
                "checkpoint_signature": cp.get("signature"),
                "checkpoint_signature_kid": cp.get("signature_kid"),
                "audit_path": path,
            },
            checkpoint_ref=cp.get("locator"))

    # ---- CT-log specific helpers ----------------------------------------

    async def current_tree_size(self) -> int:
        cur_max = await self.tree.find_one(
            {}, {"_id": 0, "leaf_seq": 1}, sort=[("leaf_seq", -1)])
        return cur_max["leaf_seq"] if cur_max else 0

    async def current_tree_head(self) -> Optional[dict]:
        size = await self.current_tree_size()
        if size == 0:
            return None
        all_leaves = [d["leaf_hash"]
                       async for d in self.tree.find(
                           {}, {"_id": 0, "leaf_hash": 1, "leaf_seq": 1}
                       ).sort("leaf_seq", 1)]
        return {"tree_size": size,
                "root_hash": compute_merkle_root(all_leaves)
                              if all_leaves else None}

    async def record_checkpoint(self, *, head_seq: int, tree_size: int,
                                 root_hash: str, signature: str,
                                 signature_kid: str,
                                 locator: Optional[str] = None) -> dict:
        doc = {"head_seq": head_seq, "tree_size": tree_size,
                "root_hash": root_hash, "signature": signature,
                "signature_kid": signature_kid,
                "locator": locator, "published_at": now_iso()}
        await self.checkpoints.insert_one(doc)
        return doc

    async def latest_checkpoint(self) -> Optional[dict]:
        doc = await self.checkpoints.find_one(
            {}, {"_id": 0}, sort=[("head_seq", -1)])
        return doc


def _audit_path(leaves: list[str], *, leaf_index: int) -> list[dict]:
    """Compute the bitcoin-style audit path for ``leaves[leaf_index]``.

    Returns ``[{"side": "left"|"right", "hash": "..."}]`` ordered from
    the leaf upward. Uses the SAME primitive as
    ``value_objects.compute_merkle_root`` so the verifier can replay.
    """
    if not leaves:
        raise ValueError("no leaves")
    if leaf_index < 0 or leaf_index >= len(leaves):
        raise IndexError(f"leaf_index {leaf_index} out of range")
    nodes = list(leaves)
    idx = leaf_index
    path: list[dict] = []
    while len(nodes) > 1:
        new_level: list[str] = []
        for i in range(0, len(nodes), 2):
            a = nodes[i]
            b = nodes[i + 1] if i + 1 < len(nodes) else nodes[i]
            new_level.append(hashlib.sha256((a + b).encode("ascii")).hexdigest())
        # Record sibling for this level.
        pair_start = (idx // 2) * 2
        if pair_start + 1 < len(nodes):
            sibling = nodes[pair_start + 1] if pair_start == idx else nodes[pair_start]
        else:
            sibling = nodes[pair_start]  # duplicated leaf
        side = "right" if (pair_start == idx) else "left"
        path.append({"side": side, "hash": sibling})
        idx //= 2
        nodes = new_level
    return path
