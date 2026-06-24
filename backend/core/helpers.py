"""Tiny pure helpers shared by every module."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str = "") -> str:
    base = uuid.uuid4().hex[:16]
    return f"{prefix}_{base}" if prefix else base


def isoformat(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def serialize_doc(doc: dict | None) -> dict | None:
    """Strip Mongo _id and ensure datetimes are ISO strings."""
    if doc is None:
        return None
    doc.pop("_id", None)
    for k, v in list(doc.items()):
        if isinstance(v, datetime):
            doc[k] = isoformat(v)
    return doc
