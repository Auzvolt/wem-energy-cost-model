"""Audit log for assumption library mutations.

Records every create, update, and delete operation on assumption entries
and sets so that changes are fully traceable by actor and timestamp.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

AuditOperation = Literal["create", "update", "delete"]


@dataclass
class AuditEntry:
    """A single row in the assumption audit log."""

    id: uuid.UUID
    set_id: uuid.UUID
    operation: AuditOperation
    actor: str
    changed_at: datetime
    entry_id: uuid.UUID | None = None
    old_value: Any | None = None
    new_value: Any | None = None


# ---------------------------------------------------------------------------
# In-memory audit store
# ---------------------------------------------------------------------------

# For scenarios that do not use a database (unit tests, CLI tools), the audit
# log is maintained as a module-level list. The async database-backed variant
# should wrap this same contract once db.assumption_orm is available.
_audit_log: list[AuditEntry] = []


def _now_utc() -> datetime:
    return datetime.now(tz=UTC)


def log_change(
    set_id: uuid.UUID,
    operation: AuditOperation,
    actor: str,
    entry_id: uuid.UUID | None = None,
    old_value: Any | None = None,
    new_value: Any | None = None,
) -> AuditEntry:
    """Append an audit entry to the in-memory log.

    Args:
        set_id: ID of the assumption set that was mutated.
        operation: One of 'create', 'update', 'delete'.
        actor: Free-text identifier for the user or process making the change.
        entry_id: Optional ID of the specific ``AssumptionEntry`` mutated.
            Pass ``None`` for set-level operations.
        old_value: Serialisable snapshot of the value before the change.
        new_value: Serialisable snapshot of the value after the change.

    Returns:
        The recorded :class:`AuditEntry`.
    """
    entry = AuditEntry(
        id=uuid.uuid4(),
        set_id=set_id,
        entry_id=entry_id,
        operation=operation,
        actor=actor,
        changed_at=_now_utc(),
        old_value=old_value,
        new_value=new_value,
    )
    _audit_log.append(entry)
    return entry


def get_audit_log(
    *,
    set_id: uuid.UUID | None = None,
    entry_id: uuid.UUID | None = None,
    actor: uuid.UUID | str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[AuditEntry]:
    """Retrieve filtered audit log entries.

    All filters are applied cumulatively (AND semantics).

    Args:
        set_id: Only return entries for this assumption set.
        entry_id: Only return entries for this assumption entry.
        actor: Only return entries by this actor.
        since: Return entries where changed_at >= since.
        until: Return entries where changed_at < until.
        limit: Maximum number of results to return.
        offset: Number of results to skip (for pagination).

    Returns:
        Filtered list of :class:`AuditEntry` objects, ordered by changed_at ascending.
    """
    results: list[AuditEntry] = list(_audit_log)

    if set_id is not None:
        results = [r for r in results if r.set_id == set_id]
    if entry_id is not None:
        results = [r for r in results if r.entry_id == entry_id]
    if actor is not None:
        results = [r for r in results if r.actor == str(actor)]
    if since is not None:
        results = [r for r in results if r.changed_at >= since]
    if until is not None:
        results = [r for r in results if r.changed_at < until]

    # Sort chronologically before slicing
    results.sort(key=lambda e: e.changed_at)
    return results[offset : offset + limit]


def clear_audit_log() -> None:
    """Clear all in-memory audit entries.

    Intended for test teardown only — do not call in production code.
    """
    _audit_log.clear()
