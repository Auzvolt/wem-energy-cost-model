"""Unit tests for app.pipeline.backfill.

All tests are fully offline — no live HTTP calls, no real DB connections.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest

from app.pipeline.backfill import (
    _checkpoint_key,
    _date_range,
    _load_checkpoint,
    _save_checkpoint,
    run_backfill,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tmp_checkpoint(tmp_path: Path, data: dict) -> Path:
    cp = tmp_path / "checkpoint.json"
    cp.write_text(json.dumps(data))
    return cp


# ---------------------------------------------------------------------------
# _date_range
# ---------------------------------------------------------------------------


def test_date_range_single_day() -> None:
    result = _date_range(date(2024, 1, 1), date(2024, 1, 1))
    assert result == [date(2024, 1, 1)]


def test_date_range_three_days() -> None:
    result = _date_range(date(2024, 1, 1), date(2024, 1, 3))
    assert result == [date(2024, 1, 1), date(2024, 1, 2), date(2024, 1, 3)]


def test_date_range_empty_when_start_after_end() -> None:
    result = _date_range(date(2024, 1, 5), date(2024, 1, 1))
    assert result == []


# ---------------------------------------------------------------------------
# Checkpoint helpers
# ---------------------------------------------------------------------------


def test_load_checkpoint_missing_file(tmp_path: Path) -> None:
    cp = tmp_path / "nonexistent.json"
    assert _load_checkpoint(cp) == {}


def test_save_and_load_checkpoint_roundtrip(tmp_path: Path) -> None:
    cp = tmp_path / "cp.json"
    data = {"2024-01-01::energy": {"status": "ok", "records_fetched": 10}}
    _save_checkpoint(cp, data)
    assert _load_checkpoint(cp) == data


def test_load_checkpoint_invalid_json(tmp_path: Path) -> None:
    cp = tmp_path / "bad.json"
    cp.write_text("{not: valid json}")
    # Should return empty dict, not raise.
    assert _load_checkpoint(cp) == {}


# ---------------------------------------------------------------------------
# Idempotency: running the same range twice should not double-upsert
# ---------------------------------------------------------------------------


def test_idempotency_run_twice(tmp_path: Path) -> None:
    """Second run over same range skips already-OK entries."""
    cp = tmp_path / "cp.json"
    call_counts: dict[str, int] = {"energy": 0, "fcess": 0}

    def _fake_energy(trading_date: date, dry_run: bool) -> int:
        call_counts["energy"] += 1
        return 5

    def _fake_fcess(trading_date: date, dry_run: bool) -> int:
        call_counts["fcess"] += 1
        return 3

    with (
        patch("app.pipeline.backfill._fetch_energy", side_effect=_fake_energy),
        patch("app.pipeline.backfill._fetch_fcess", side_effect=_fake_fcess),
    ):
        run_backfill(date(2024, 1, 1), date(2024, 1, 3), ["energy", "fcess"], checkpoint_path=cp)
        # Second run — should skip all (already "ok")
        run_backfill(date(2024, 1, 1), date(2024, 1, 3), ["energy", "fcess"], checkpoint_path=cp)

    # 3 days × 1 product = 3 calls each on first run; 0 on second run
    assert call_counts["energy"] == 3
    assert call_counts["fcess"] == 3


# ---------------------------------------------------------------------------
# Checkpoint: mid-run failure → checkpoint written → resume skips ok entries
# ---------------------------------------------------------------------------


def test_checkpoint_written_on_partial_failure(tmp_path: Path) -> None:
    """Checkpoint tracks successful days; failed day is retryable."""
    cp = tmp_path / "cp.json"

    call_log: list[str] = []

    def _fake_energy(trading_date: date, dry_run: bool) -> int:
        key = f"{trading_date}"
        call_log.append(key)
        if trading_date == date(2024, 1, 2):
            raise RuntimeError("simulated API failure")
        return 4

    with patch("app.pipeline.backfill._fetch_energy", side_effect=_fake_energy):
        run_backfill(date(2024, 1, 1), date(2024, 1, 3), ["energy"], checkpoint_path=cp)

    checkpoint = _load_checkpoint(cp)
    assert checkpoint[_checkpoint_key(date(2024, 1, 1), "energy")]["status"] == "ok"
    assert checkpoint[_checkpoint_key(date(2024, 1, 2), "energy")]["status"] == "error"
    assert checkpoint[_checkpoint_key(date(2024, 1, 3), "energy")]["status"] == "ok"


def test_resume_skips_ok_retries_error(tmp_path: Path) -> None:
    """On second run, ok days are skipped and error day is retried."""
    cp = tmp_path / "cp.json"

    # Pre-seed checkpoint: day 1 ok, day 2 error
    _save_checkpoint(
        cp,
        {
            _checkpoint_key(date(2024, 1, 1), "energy"): {"status": "ok", "records_fetched": 4},
            _checkpoint_key(date(2024, 1, 2), "energy"): {
                "status": "error",
                "records_fetched": 0,
                "error_msg": "simulated API failure",
            },
        },
    )

    call_log: list[date] = []

    def _fake_energy(trading_date: date, dry_run: bool) -> int:
        call_log.append(trading_date)
        return 4

    with patch("app.pipeline.backfill._fetch_energy", side_effect=_fake_energy):
        run_backfill(date(2024, 1, 1), date(2024, 1, 2), ["energy"], checkpoint_path=cp)

    # Only day 2 should have been retried
    assert call_log == [date(2024, 1, 2)]

    checkpoint = _load_checkpoint(cp)
    assert checkpoint[_checkpoint_key(date(2024, 1, 2), "energy")]["status"] == "ok"


# ---------------------------------------------------------------------------
# Partial failure: one product failing should not block other products
# ---------------------------------------------------------------------------


def test_partial_failure_does_not_block_other_products(tmp_path: Path) -> None:
    """If energy fails for a day, fcess for that same day still completes."""
    cp = tmp_path / "cp.json"

    fcess_dates: list[date] = []

    def _fail_energy(trading_date: date, dry_run: bool) -> int:
        raise RuntimeError("energy API down")

    def _ok_fcess(trading_date: date, dry_run: bool) -> int:
        fcess_dates.append(trading_date)
        return 2

    with (
        patch("app.pipeline.backfill._fetch_energy", side_effect=_fail_energy),
        patch("app.pipeline.backfill._fetch_fcess", side_effect=_ok_fcess),
    ):
        run_backfill(date(2024, 1, 1), date(2024, 1, 1), ["energy", "fcess"], checkpoint_path=cp)

    checkpoint = _load_checkpoint(cp)
    assert checkpoint[_checkpoint_key(date(2024, 1, 1), "energy")]["status"] == "error"
    assert checkpoint[_checkpoint_key(date(2024, 1, 1), "fcess")]["status"] == "ok"
    assert date(2024, 1, 1) in fcess_dates


# ---------------------------------------------------------------------------
# Dry-run: no DB writes, no checkpoint written
# ---------------------------------------------------------------------------


def test_dry_run_no_db_writes(tmp_path: Path) -> None:
    """Dry-run should not invoke real fetchers and should not write checkpoint."""
    cp = tmp_path / "cp.json"

    energy_called = False
    fcess_called = False

    def _spy_energy(trading_date: date, dry_run: bool) -> int:
        nonlocal energy_called
        if not dry_run:
            energy_called = True
        return 0

    def _spy_fcess(trading_date: date, dry_run: bool) -> int:
        nonlocal fcess_called
        if not dry_run:
            fcess_called = True
        return 0

    with (
        patch("app.pipeline.backfill._fetch_energy", side_effect=_spy_energy),
        patch("app.pipeline.backfill._fetch_fcess", side_effect=_spy_fcess),
    ):
        run_backfill(
            date(2024, 1, 1),
            date(2024, 1, 2),
            ["energy", "fcess"],
            dry_run=True,
            checkpoint_path=cp,
        )

    assert not energy_called, "Energy fetcher should not write to DB in dry-run"
    assert not fcess_called, "FCESS fetcher should not write to DB in dry-run"
    # Checkpoint should NOT be written during dry-run
    assert not cp.exists(), "Checkpoint file should not be created during dry-run"


# ---------------------------------------------------------------------------
# CLI argument parsing
# ---------------------------------------------------------------------------


def test_main_invalid_date_exits(capsys: pytest.CaptureFixture[str]) -> None:
    """main() should exit with code 1 for invalid date formats."""
    from app.pipeline.backfill import main

    with pytest.raises(SystemExit) as exc_info:
        main(["--start", "not-a-date", "--end", "2024-01-31"])

    assert exc_info.value.code == 1


def test_main_start_after_end_exits() -> None:
    from app.pipeline.backfill import main

    with pytest.raises(SystemExit) as exc_info:
        main(["--start", "2024-03-01", "--end", "2024-01-01"])

    assert exc_info.value.code == 1


def test_main_invalid_product_exits() -> None:
    from app.pipeline.backfill import main

    with pytest.raises(SystemExit) as exc_info:
        main(["--start", "2024-01-01", "--end", "2024-01-01", "--products", "invalid_product"])

    assert exc_info.value.code == 1
