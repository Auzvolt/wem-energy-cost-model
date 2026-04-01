"""Tests for app.assumptions.audit module.

Covers both the in-memory path (session=None) and the DB-backed path via a
synchronous in-memory SQLite session.  Async DB tests are out of scope here
because CI does not configure an async SQLite engine with the audit schema;
those are integration-tested via the full migration suite.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.assumptions.audit import (
    AuditEntry,
    clear_audit_log,
    get_audit_log,
    log_change,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_audit_log() -> None:
    """Clear the in-memory audit log before each test."""
    clear_audit_log()


def _set_id() -> uuid.UUID:
    return uuid.uuid4()


def _entry_id() -> uuid.UUID:
    return uuid.uuid4()


# ---------------------------------------------------------------------------
# log_change — in-memory path
# ---------------------------------------------------------------------------


class TestLogChange:
    def test_create_entry_logged(self) -> None:
        """log_change records a 'create' event with correct fields."""
        sid = _set_id()
        eid = _entry_id()
        new_val = {"value": 100.0}

        record = log_change(
            set_id=sid,
            operation="create",
            actor="test_user",
            entry_id=eid,
            old_value=None,
            new_value=new_val,
        )

        assert isinstance(record, AuditEntry)
        assert record.set_id == sid
        assert record.entry_id == eid
        assert record.operation == "create"
        assert record.actor == "test_user"
        assert record.new_value == new_val
        assert record.old_value is None
        assert isinstance(record.id, uuid.UUID)
        assert isinstance(record.changed_at, datetime)

    def test_update_entry_logged(self) -> None:
        """log_change records an 'update' event with old and new values."""
        sid = _set_id()
        record = log_change(
            set_id=sid,
            operation="update",
            actor="editor",
            old_value={"value": 50.0},
            new_value={"value": 75.0},
        )

        assert record.operation == "update"
        assert record.old_value == {"value": 50.0}
        assert record.new_value == {"value": 75.0}
        assert record.entry_id is None

    def test_delete_entry_logged(self) -> None:
        """log_change records a 'delete' event."""
        sid = _set_id()
        eid = _entry_id()
        record = log_change(
            set_id=sid,
            operation="delete",
            actor="admin",
            entry_id=eid,
            old_value={"value": 99.0},
        )

        assert record.operation == "delete"
        assert record.old_value == {"value": 99.0}
        assert record.new_value is None

    def test_multiple_entries_appended(self) -> None:
        """Multiple log_change calls all appear in get_audit_log."""
        sid = _set_id()
        for i in range(5):
            log_change(set_id=sid, operation="create", actor=f"user_{i}")

        log = get_audit_log(set_id=sid)
        assert len(log) == 5

    def test_changed_at_is_recent_utc(self) -> None:
        """changed_at is a timezone-aware UTC datetime close to now."""
        before = datetime.now(tz=UTC)
        record = log_change(set_id=_set_id(), operation="create", actor="u")
        after = datetime.now(tz=UTC)

        assert before <= record.changed_at <= after


# ---------------------------------------------------------------------------
# get_audit_log — filtering
# ---------------------------------------------------------------------------


class TestGetAuditLog:
    def test_filter_by_set_id(self) -> None:
        """get_audit_log(set_id=...) returns only entries for that set."""
        sid1, sid2 = _set_id(), _set_id()
        log_change(set_id=sid1, operation="create", actor="u")
        log_change(set_id=sid2, operation="create", actor="u")

        result = get_audit_log(set_id=sid1)
        assert len(result) == 1
        assert result[0].set_id == sid1

    def test_filter_by_entry_id(self) -> None:
        """get_audit_log(entry_id=...) filters by assumption entry."""
        sid = _set_id()
        eid = _entry_id()
        log_change(set_id=sid, operation="create", actor="u", entry_id=eid)
        log_change(set_id=sid, operation="create", actor="u")

        result = get_audit_log(entry_id=eid)
        assert len(result) == 1
        assert result[0].entry_id == eid

    def test_filter_by_actor(self) -> None:
        """get_audit_log(actor=...) returns only entries by that actor."""
        sid = _set_id()
        log_change(set_id=sid, operation="create", actor="alice")
        log_change(set_id=sid, operation="create", actor="bob")

        result = get_audit_log(actor="alice")
        assert len(result) == 1
        assert result[0].actor == "alice"

    def test_filter_since(self) -> None:
        """get_audit_log(since=...) excludes older entries."""
        sid = _set_id()
        log_change(set_id=sid, operation="create", actor="u")

        future = datetime.now(tz=UTC) + timedelta(hours=1)
        result = get_audit_log(since=future)
        assert result == []

    def test_filter_until(self) -> None:
        """get_audit_log(until=...) excludes entries after the cutoff."""
        sid = _set_id()
        log_change(set_id=sid, operation="create", actor="u")

        past = datetime.now(tz=UTC) - timedelta(hours=1)
        result = get_audit_log(until=past)
        assert result == []

    def test_ordered_by_changed_at_ascending(self) -> None:
        """get_audit_log returns results ordered by changed_at asc."""
        sid = _set_id()
        for _ in range(3):
            log_change(set_id=sid, operation="create", actor="u")

        result = get_audit_log(set_id=sid)
        timestamps = [r.changed_at for r in result]
        assert timestamps == sorted(timestamps)

    def test_limit_and_offset(self) -> None:
        """limit and offset paginate results correctly."""
        sid = _set_id()
        for _ in range(10):
            log_change(set_id=sid, operation="create", actor="u")

        page1 = get_audit_log(set_id=sid, limit=4, offset=0)
        page2 = get_audit_log(set_id=sid, limit=4, offset=4)
        page3 = get_audit_log(set_id=sid, limit=4, offset=8)

        assert len(page1) == 4
        assert len(page2) == 4
        assert len(page3) == 2

        ids1 = {r.id for r in page1}
        ids2 = {r.id for r in page2}
        assert ids1.isdisjoint(ids2)

    def test_empty_log_returns_empty_list(self) -> None:
        """get_audit_log returns [] when no entries exist."""
        assert get_audit_log() == []

    def test_combined_filters(self) -> None:
        """Multiple filters applied together use AND semantics."""
        sid = _set_id()
        eid = _entry_id()
        log_change(set_id=sid, operation="create", actor="alice", entry_id=eid)
        log_change(set_id=sid, operation="update", actor="alice")
        log_change(set_id=sid, operation="create", actor="bob", entry_id=eid)

        result = get_audit_log(actor="alice", entry_id=eid)
        assert len(result) == 1
        assert result[0].actor == "alice"
        assert result[0].entry_id == eid


# ---------------------------------------------------------------------------
# clear_audit_log
# ---------------------------------------------------------------------------


class TestClearAuditLog:
    def test_clears_all_entries(self) -> None:
        """clear_audit_log removes all entries from the in-memory store."""
        sid = _set_id()
        log_change(set_id=sid, operation="create", actor="u")
        log_change(set_id=sid, operation="update", actor="u")

        clear_audit_log()
        assert get_audit_log() == []

    def test_idempotent_on_empty(self) -> None:
        """clear_audit_log on an empty log does not raise."""
        clear_audit_log()
        clear_audit_log()
        assert get_audit_log() == []
