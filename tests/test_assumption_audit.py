"""Tests for app.assumptions.audit module."""

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
# log_change tests
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
        assert record.old_value is None
        assert record.new_value == new_val

    def test_update_entry_logged(self) -> None:
        """log_change records an 'update' event with both old and new values."""
        sid = _set_id()
        eid = _entry_id()
        old = {"value": 50.0}
        new = {"value": 75.0}

        log_change(
            set_id=sid, operation="update", actor="dev", entry_id=eid, old_value=old, new_value=new
        )
        entries = get_audit_log(entry_id=eid)

        assert len(entries) == 1
        assert entries[0].operation == "update"
        assert entries[0].old_value == old
        assert entries[0].new_value == new

    def test_delete_entry_logged(self) -> None:
        """log_change records a 'delete' event."""
        sid = _set_id()
        eid = _entry_id()

        log_change(
            set_id=sid, operation="delete", actor="admin", entry_id=eid, old_value={"value": 99.0}
        )
        entries = get_audit_log(entry_id=eid)

        assert len(entries) == 1
        assert entries[0].operation == "delete"
        assert entries[0].new_value is None

    def test_returns_audit_entry(self) -> None:
        record = log_change(set_id=_set_id(), operation="create", actor="x")
        assert isinstance(record, AuditEntry)

    def test_changed_at_utc(self) -> None:
        """changed_at is timezone-aware UTC."""
        before = datetime.now(tz=UTC)
        log_change(set_id=_set_id(), operation="create", actor="x")
        after = datetime.now(tz=UTC)

        entries = get_audit_log()
        assert len(entries) == 1
        assert before <= entries[0].changed_at <= after


# ---------------------------------------------------------------------------
# get_audit_log filter tests
# ---------------------------------------------------------------------------


class TestGetAuditLog:
    def test_filter_by_set_id(self) -> None:
        sid_a = _set_id()
        sid_b = _set_id()
        log_change(set_id=sid_a, operation="create", actor="a")
        log_change(set_id=sid_b, operation="create", actor="b")
        log_change(set_id=sid_a, operation="update", actor="a")

        results = get_audit_log(set_id=sid_a)
        assert len(results) == 2
        assert all(r.set_id == sid_a for r in results)

    def test_filter_by_entry_id(self) -> None:
        sid = _set_id()
        eid_x = _entry_id()
        eid_y = _entry_id()
        log_change(set_id=sid, operation="create", actor="a", entry_id=eid_x)
        log_change(set_id=sid, operation="update", actor="a", entry_id=eid_y)
        log_change(set_id=sid, operation="update", actor="a", entry_id=eid_x)

        results = get_audit_log(entry_id=eid_x)
        assert len(results) == 2

    def test_filter_by_since(self) -> None:
        sid = _set_id()
        now = datetime.now(tz=UTC)
        future = now + timedelta(hours=1)

        log_change(set_id=sid, operation="create", actor="early")

        results = get_audit_log(since=future)
        assert len(results) == 0

        results = get_audit_log(since=now - timedelta(seconds=1))
        assert len(results) == 1

    def test_filter_by_until(self) -> None:
        sid = _set_id()
        log_change(set_id=sid, operation="create", actor="x")

        now = datetime.now(tz=UTC)
        results = get_audit_log(until=now + timedelta(seconds=1))
        assert len(results) == 1

        results = get_audit_log(until=now - timedelta(hours=1))
        assert len(results) == 0

    def test_pagination_limit_offset(self) -> None:
        sid = _set_id()
        for i in range(5):
            log_change(set_id=sid, operation="create", actor=f"user_{i}")

        page_1 = get_audit_log(set_id=sid, limit=2, offset=0)
        page_2 = get_audit_log(set_id=sid, limit=2, offset=2)
        page_3 = get_audit_log(set_id=sid, limit=2, offset=4)

        assert len(page_1) == 2
        assert len(page_2) == 2
        assert len(page_3) == 1

    def test_ordered_chronologically(self) -> None:
        """Results are sorted by changed_at ascending."""
        sid = _set_id()
        for _ in range(3):
            log_change(set_id=sid, operation="create", actor="x")

        results = get_audit_log(set_id=sid)
        timestamps = [r.changed_at for r in results]
        assert timestamps == sorted(timestamps)

    def test_empty_log_returns_empty_list(self) -> None:
        assert get_audit_log() == []

    def test_create_has_none_old_value(self) -> None:
        """A create audit entry has old_value = None."""
        sid = _set_id()
        log_change(set_id=sid, operation="create", actor="x", new_value={"v": 1})
        entries = get_audit_log()
        assert entries[0].old_value is None

    def test_multiple_operations_accumulated(self) -> None:
        sid = _set_id()
        eid = _entry_id()
        log_change(set_id=sid, operation="create", actor="user", entry_id=eid, new_value={"v": 1})
        log_change(
            set_id=sid,
            operation="update",
            actor="user",
            entry_id=eid,
            old_value={"v": 1},
            new_value={"v": 2},
        )

        all_entries = get_audit_log(entry_id=eid)
        assert len(all_entries) == 2
        assert all_entries[0].operation == "create"
        assert all_entries[1].operation == "update"
