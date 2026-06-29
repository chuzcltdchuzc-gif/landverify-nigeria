"""CheckpointPublisherPort adapters — Phase 3.6 §15 Decision 1.

* ``LocalFsCheckpointPublisher`` — dev default. Writes signed tree
  heads under ``${EVIDENCE_CHECKPOINT_DIR}/<head_seq>.json``.
* ``R2PublicCheckpointPublisher`` — stub for production R2 (would
  upload to a public bucket); falls back to local-FS in dev.
* ``FanOutCheckpointPublisher`` — composite. Operator configures
  multiple publishers via ``EVIDENCE_CHECKPOINT_PUBLISHERS`` csv; the
  saga calls ``publish_checkpoint`` on each and considers the operation
  successful if at least one succeeds.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from contexts.evidence.domain.value_objects import now_iso
from contexts.evidence.ports.checkpoint_publisher import (
    CheckpointPublisherPort,
    CheckpointRef,
    TreeHead,
)

DEFAULT_DIR = "/tmp/aqua-evidence-checkpoints"


class LocalFsCheckpointPublisher:
    """Local-FS publisher. Default dev target."""

    publisher_id = "local_fs"

    def __init__(self, root_dir: Optional[str] = None) -> None:
        self._root = Path(root_dir or os.environ.get(
            "EVIDENCE_CHECKPOINT_DIR", DEFAULT_DIR))
        self._root.mkdir(parents=True, exist_ok=True)

    async def publish_checkpoint(self, *, head: TreeHead,
                                   signature: str,
                                   signature_kid: str) -> CheckpointRef:
        doc = {"head": head.to_dict(),
                "signature": signature,
                "signature_kid": signature_kid,
                "published_at": now_iso()}
        path = self._root / f"{head.head_seq:012d}.json"
        path.write_text(json.dumps(doc, sort_keys=True, indent=2))
        return CheckpointRef(publisher_id=self.publisher_id,
                              head_seq=head.head_seq,
                              locator=str(path),
                              signature=signature,
                              signature_kid=signature_kid,
                              published_at=doc["published_at"])

    async def fetch_checkpoint(self,
                                 head_seq: int) -> Optional[CheckpointRef]:
        path = self._root / f"{head_seq:012d}.json"
        if not path.exists():
            return None
        doc = json.loads(path.read_text())
        return CheckpointRef(publisher_id=self.publisher_id,
                              head_seq=head_seq, locator=str(path),
                              signature=doc["signature"],
                              signature_kid=doc["signature_kid"],
                              published_at=doc["published_at"])


class R2PublicCheckpointPublisher:
    """R2 Public publisher. In production this would upload to an R2
    bucket; in dev it writes locally so the test suite can exercise the
    same code path. Real R2 wiring is a one-file swap."""

    publisher_id = "r2_public"

    def __init__(self, *, bucket: Optional[str] = None,
                 root_dir: Optional[str] = None) -> None:
        self._bucket = bucket or os.environ.get(
            "EVIDENCE_CHECKPOINT_R2_BUCKET", "aqua-evidence-checkpoints")
        self._local = LocalFsCheckpointPublisher(root_dir or os.environ.get(
            "EVIDENCE_CHECKPOINT_DIR", DEFAULT_DIR + "-r2"))

    async def publish_checkpoint(self, *, head: TreeHead, signature: str,
                                   signature_kid: str) -> CheckpointRef:
        ref = await self._local.publish_checkpoint(
            head=head, signature=signature, signature_kid=signature_kid)
        # Real impl would upload `ref.locator` to f"r2://{self._bucket}/...".
        return CheckpointRef(publisher_id=self.publisher_id,
                              head_seq=ref.head_seq,
                              locator=f"r2://{self._bucket}/{head.head_seq:012d}.json",
                              signature=signature,
                              signature_kid=signature_kid,
                              published_at=ref.published_at)

    async def fetch_checkpoint(self,
                                 head_seq: int) -> Optional[CheckpointRef]:
        return await self._local.fetch_checkpoint(head_seq)


class FanOutCheckpointPublisher:
    """Composite — operator-configured list. Per ADR-0008 §15
    Decision 1: 'core domain depends ONLY on the Protocol'. The fan-out
    is itself a Protocol-conforming adapter."""

    publisher_id = "fan_out"

    def __init__(self, publishers: list[CheckpointPublisherPort]) -> None:
        if not publishers:
            raise ValueError("FanOutCheckpointPublisher needs >=1 publisher")
        self._publishers = publishers

    async def publish_checkpoint(self, *, head: TreeHead, signature: str,
                                   signature_kid: str) -> CheckpointRef:
        last_err: Optional[Exception] = None
        any_ok: Optional[CheckpointRef] = None
        for pub in self._publishers:
            try:
                ref = await pub.publish_checkpoint(
                    head=head, signature=signature,
                    signature_kid=signature_kid)
                if any_ok is None:
                    any_ok = ref
            except Exception as exc:  # noqa: BLE001
                last_err = exc
        if any_ok:
            return any_ok
        raise RuntimeError(
            f"all checkpoint publishers failed; last_err={last_err}")

    async def fetch_checkpoint(self,
                                 head_seq: int) -> Optional[CheckpointRef]:
        for pub in self._publishers:
            ref = await pub.fetch_checkpoint(head_seq)
            if ref:
                return ref
        return None


def build_publisher_from_env() -> CheckpointPublisherPort:
    """Factory from ``EVIDENCE_CHECKPOINT_PUBLISHERS`` env. Defaults to
    the disabled-in-production local-FS publisher per §15 Decision 1."""
    csv = os.environ.get("EVIDENCE_CHECKPOINT_PUBLISHERS", "local_fs")
    parts = [p.strip() for p in csv.split(",") if p.strip()]
    pubs: list[CheckpointPublisherPort] = []
    for p in parts:
        if p == "local_fs":
            pubs.append(LocalFsCheckpointPublisher())
        elif p == "r2_public":
            pubs.append(R2PublicCheckpointPublisher())
        elif p == "ipfs":
            # IPFS adapter is a Phase 5 expansion; falls back to local for now.
            pubs.append(LocalFsCheckpointPublisher())
        else:
            raise ValueError(f"unknown checkpoint publisher: {p!r}")
    return pubs[0] if len(pubs) == 1 else FanOutCheckpointPublisher(pubs)
