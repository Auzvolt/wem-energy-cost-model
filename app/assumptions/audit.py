"""Audit log for assumption library mutations.

Records every create, update, and delete operation on assumption entries
and sets so that changes are fully traceable by actor and timestamp.

Audit rows are written inside the same DB transaction as the mutation when
a SQLAlchemy session is supplied to ``log_change()`` /
``log_change_async()``.  When no session is provided (e.g. unit tests),
entries fall back to the module-level in-memory list.
``clear_audit_log()`` is provided for test teardown only.
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
# In-memory fallback (test helper only)
# ---------------------------------------------------------------------------

_audit_log: list[AuditEntry] = []

_INSERT_SQL = """
    INSERT INTO assumption_audit_log
        (id, set_id, entry_id, operation, actor, changed_at, old_value, new_value)
    VALUES
        (:id, :set_id, :entry_id, CAST(:operation AS audit_operation),
         :actor, :changed_at, CAST(:old_value AS jsonb), CAST(:new_value AS jsonb))
"""


def _now_utc() -> datetime:
    return datetime.now(tz=UTC)


def _build_params(entry: AuditEntry) -> dict[str, Any]:
    return {
        "id": str(entry.id),
        "set_id": str(entry.set_id),
        "entry_id": str(entry.entry_id) if entry.entry_id is not None else None,
        "operation": entry.operation,
        "actor": entry.actor,
        "changed_at": entry.changed_at,
        "old_value": _to_json(entry.old_value),
        "new_value": _to_json(entry.new_value),
    }


def _to_json(value: Any) -> str | None:
    if value is None:
        return None
    import json  # noqa: PLC0415

    return json.dumps(value, default=str)


def _make_entry(
    set_id: uuid.UUID,
    operation: AuditOperation,
    actor: str,
    entry_id: uuid.UUID | None,
    old_value: Any | None,
    new_value: Any | None,
) -> AuditEntry:
    return AuditEntry(
        id=uuid.uuid4(),
        set_id=set_id,
        entry_id=entry_id,
        operation=operation,
        actor=actor,
        changed_at=_now_utc(),
        old_value=old_value,
        new_value=new_value,
    )


# ---------------------------------------------------------------------------
# Sync API
# ---------------------------------------------------------------------------


def log_change(
    set_id: uuid.UUID,
    operation: AuditOperation,
    actor: str,
    entry_id: uuid.UUID | None = None,
    old_value: Any | None = None,
    new_value: Any | None = None,
    *,
    session: Any | None = None,
) -> AuditEntry:
    """Record an audit entry (sync).

    When *session* is supplied the row is inserted into ``assumption_audit_log``
    via the same SQLAlchemy sync session — ensuring atomicity with the
    surrounding transaction.  The caller is responsible for commit/rollback.

    When *session* is ``None`` the entry is stored in the module-level
    in-memory list (test mode).

    Args:
        set_id: ID of the assumption set that was mutated.
        operation: One of ``'create'``, ``'update'``, or ``'delete'``.
        actor: Opaque user/process identifier.  Must not contain PII such as
            full names or email addresses — use a user-id string.
        entry_id: Optional ID of the specific ``AssumptionEntry`` mutated.
        old_value: JSON-serialisable snapshot before the change.
        new_value: JSON-serialisable snapshot after the change.
        session: Optional SQLAlchemy sync ``Session``.

    Returns:
        The recorded :class:`AuditEntry`.
    """
    entry = _make_entry(set_id, operation, actor, entry_id, old_value, new_value)
    if session is not None:
        from sqlalchemy import text  # noqa: PLC0415

        session.execute(text(_INSERT_SQL), _build_params(entry))
    else:
        _audit_log.append(entry)
    return entry


# ---------------------------------------------------------------------------
# Async API
# ---------------------------------------------------------------------------


async def log_change_async(
    set_id: uuid.UUID,
    operation: AuditOperation,
    actor: str,
    entry_id: uuid.UUID | None = None,
    old_value: Any | None = None,
    new_value: Any | None = None,
    *,
    session: Any | None = None,
) -> AuditEntry:
    """Record an audit entry (async).

    Identical to :func:`log_change` but accepts a SQLAlchemy
    ``AsyncSession``.  When *session* is ``None`` the entry falls back to
    the in-memory list.

    Args:
        set_id: ID of the assumption set that was mutated.
        operation: One of ``'create'``, ``'update'``, or ``'delete'``.
        actor: Opaque user/process identifier (no PII).
        entry_id: Optional ID of the specific ``AssumptionEntry`` mutated.
        old_value: JSON-serialisable snapshot before the change.
        new_value: JSON-serialisable snapshot after the change.
        session: Optional SQLAlchemy ``AsyncSession``.

    Returns:
        The recorded :class:`AuditEntry`.
    """
    entry = _make_entry(set_id, operation, actor, entry_id, old_value, new_value)
    if session is not None:
        from sqlalchemy import text  # noqa: PLC0415

        await session.execute(text(_INSERT_SQL), _build_params(entry))
    else:
        _audit_log.append(entry)
    return entry


# ---------------------------------------------------------------------------
# Query (sync)
# ---------------------------------------------------------------------------


def get_audit_log(
    *,
    set_id: uuid.UUID | None = None,
    entry_id: uuid.UUID | None = None,
    actor: uuid.UUID | str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = 100,
    offset: int = 0,
    session: Any | None = None,
) -> list[AuditEntry]:
    """Retrieve filtered audit log entries (sync).

    Queries the database when *session* is supplied; otherwise searches the
    in-memory list.

    Args:
        set_id: Only return entries for this assumption set.
        entry_id: Only return entries for this assumption entry.
        actor: Only return entries by this actor.
        since: Return entries where ``changed_at >= since``.
        until: Return entries where ``changed_at < until``.
        limit: Maximum number of results to return.
        offset: Number of results to skip (for pagination).
        session: Optional SQLAlchemy sync ``Session``.

    Returns:
        Filtered list of :class:`AuditEntry` objects ordered by
        ``changed_at`` ascending.
    """
    if session is not None:
        return _query_db_sync(
            session,
            set_id=set_id,
            entry_id=entry_id,
            actor=actor,
            since=since,
            until=until,
            limit=limit,
            offset=offset,
        )
    return _query_memory(
        set_id=set_id,
        entry_id=entry_id,
        actor=actor,
        since=since,
        until=until,
        limit=limit,
        offset=offset,
    )


def _query_memory(
    *,
    set_id: uuid.UUID | None,
    entry_id: uuid.UUID | None,
    actor: uuid.UUID | str | None,
    since: datetime | None,
    until: datetime | None,
    limit: int,
    offset: int,
) -> list[AuditEntry]:
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
    results.sort(key=lambda e: e.changed_at)
    return results[offset : offset + limit]


def _query_db_sync(
    session: Any,
    *,
    set_id: uuid.UUID | None,
    entry_id: uuid.UUID | None,
    actor: uuid.UUID | str | None,
    since: datetime | None,
    until: datetime | None,
    limit: int,
    offset: int,
) -> list[AuditEntry]:
    from sqlalchemy import text  # noqa: PLC0415

    conditions = ["1=1"]
    params: dict[str, Any] = {"limit": limit, "offset": offset}

    if set_id is not None:
        conditions.append("set_id = :set_id")
        params["set_id"] = str(set_id)
    if entry_id is not None:
        conditions.append("entry_id = :entry_id")
        params["entry_id"] = str(entry_id)
    if actor is not None:
        conditions.append("actor = :actor")
        params["actor"] = str(actor)
    if since is not None:
        conditions.append("changed_at >= :since")
        params["since"] = since
    if until is not None:
        conditions.append("changed_at < :until")
        params["until"] = until

    sql = text(
        f"SELECT id, set_id, entry_id, operation, actor, changed_at, old_value, new_value"  # noqa: S608
        f" FROM assumption_audit_log"
        f" WHERE {' AND '.join(conditions)}"
        f" ORDER BY changed_at ASC"
        f" LIMIT :limit OFFSET :offset"
    )

    return _rows_to_entries(session.execute(sql, params).fetchall())


def _rows_to_entries(rows: list[Any]) -> list[AuditEntry]:
    import json  # noqa: PLC0415

    entries: list[AuditEntry] = []
    for row in rows:
        entries.append(
            AuditEntry(
                id=uuid.UUID(str(row.id)),
                set_id=uuid.UUID(str(row.set_id)),
                entry_id=uuid.UUID(str(row.entry_id)) if row.entry_id else None,
                operation=row.operation,
                actor=row.actor,
                changed_at=row.changed_at,
                old_value=json.loads(row.old_value) if row.old_value else None,
                new_value=json.loads(row.new_value) if row.new_value else None,
            )
        )
    return entries


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def clear_audit_log() -> None:
    """Clear all in-memory audit entries.

    Intended for test teardown only — do not call in production code.
    """
    _audit_log.clear()
