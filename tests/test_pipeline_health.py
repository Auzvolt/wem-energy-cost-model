"""Tests for pipeline health checks and alerting (issue #47)."""

from __future__ import annotations

import io
import json
import sys
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

from app.pipeline.alerts import AlertChannel, get_alert_channel, send_alert
from app.pipeline.health import (
    check_data_gap,
    check_duplicate_run,
    check_fetch_failure,
    check_schema_change,
)

# ---------------------------------------------------------------------------
# check_fetch_failure
# ---------------------------------------------------------------------------


class TestCheckFetchFailure:
    def test_ok_when_no_error_and_rows(self) -> None:
        result = check_fetch_failure({"rows": 10})
        assert result["ok"] is True
        assert result["check"] == "fetch_failure"

    def test_fail_when_error_present(self) -> None:
        result = check_fetch_failure({"error": "HTTP 503", "rows": 0})
        assert result["ok"] is False
        assert "HTTP 503" in result["detail"]

    def test_fail_when_rows_zero(self) -> None:
        result = check_fetch_failure({"rows": 0})
        assert result["ok"] is False
        assert "empty" in result["detail"].lower() or "0 rows" in result["detail"]

    def test_ok_when_rows_missing_defaults_to_nonzero(self) -> None:
        # No rows key — default is 1 so should pass
        result = check_fetch_failure({})
        assert result["ok"] is True


# ---------------------------------------------------------------------------
# check_data_gap
# ---------------------------------------------------------------------------


class TestCheckDataGap:
    def _make_session(self, latest: datetime | None) -> MagicMock:
        row = MagicMock()
        row.latest = latest
        session = MagicMock()
        session.execute.return_value.fetchone.return_value = row
        return session

    def test_fail_when_timestamp_too_old(self) -> None:
        old_ts = datetime.now(tz=UTC) - timedelta(hours=30)
        session = self._make_session(old_ts)
        result = check_data_gap(session, "ENERGY", threshold_hours=25)
        assert result["ok"] is False
        assert "30." in result["detail"] or "30" in result["detail"]

    def test_ok_when_timestamp_recent(self) -> None:
        recent_ts = datetime.now(tz=UTC) - timedelta(hours=2)
        session = self._make_session(recent_ts)
        result = check_data_gap(session, "ENERGY", threshold_hours=25)
        assert result["ok"] is True

    def test_fail_when_no_rows(self) -> None:
        row = MagicMock()
        row.latest = None
        session = MagicMock()
        session.execute.return_value.fetchone.return_value = row
        result = check_data_gap(session, "ENERGY")
        assert result["ok"] is False
        assert "No market_prices" in result["detail"]

    def test_naive_timestamp_treated_as_utc(self) -> None:
        # Naive timestamp 2 hours old should pass
        naive_ts = datetime.utcnow() - timedelta(hours=2)
        session = self._make_session(naive_ts)
        result = check_data_gap(session, "ENERGY", threshold_hours=25)
        assert result["ok"] is True


# ---------------------------------------------------------------------------
# check_schema_change
# ---------------------------------------------------------------------------


class TestCheckSchemaChange:
    def test_ok_when_all_columns_present(self) -> None:
        result = check_schema_change(["a", "b", "c"], ["a", "b", "c", "d"])
        assert result["ok"] is True

    def test_fail_when_column_missing(self) -> None:
        result = check_schema_change(["a", "b", "c"], ["a", "b"])
        assert result["ok"] is False
        assert "c" in result["detail"]

    def test_fail_lists_all_missing_columns(self) -> None:
        result = check_schema_change(["x", "y", "z"], ["x"])
        assert result["ok"] is False
        assert "y" in result["detail"]
        assert "z" in result["detail"]

    def test_ok_exact_match(self) -> None:
        cols = ["timestamp", "product", "price"]
        result = check_schema_change(cols, cols)
        assert result["ok"] is True


# ---------------------------------------------------------------------------
# check_duplicate_run
# ---------------------------------------------------------------------------


class TestCheckDuplicateRun:
    def test_fail_when_zero_rows(self) -> None:
        result = check_duplicate_run(0)
        assert result["ok"] is False
        assert "duplicate" in result["detail"].lower() or "No new rows" in result["detail"]

    def test_ok_when_rows_inserted(self) -> None:
        result = check_duplicate_run(5)
        assert result["ok"] is True
        assert "5" in result["detail"]

    def test_ok_for_single_row(self) -> None:
        result = check_duplicate_run(1)
        assert result["ok"] is True


# ---------------------------------------------------------------------------
# send_alert — LOG channel
# ---------------------------------------------------------------------------


class TestSendAlertLogChannel:
    def test_log_channel_writes_json_to_stderr(self) -> None:
        buf = io.StringIO()
        with patch.object(sys, "stderr", buf):
            send_alert("test_check", "something went wrong", AlertChannel.LOG)

        output = buf.getvalue().strip()
        assert output, "Expected JSON output on stderr"
        data = json.loads(output)
        assert data["alert"] == "test_check"
        assert data["detail"] == "something went wrong"
        assert "timestamp" in data

    def test_log_channel_timestamp_is_iso_format(self) -> None:
        buf = io.StringIO()
        with patch.object(sys, "stderr", buf):
            send_alert("ts_check", "details", AlertChannel.LOG)

        data = json.loads(buf.getvalue().strip())
        # Should parse without error
        datetime.fromisoformat(data["timestamp"])

    def test_get_alert_channel_defaults_to_log(self) -> None:
        with patch.dict("os.environ", {}, clear=False):
            # Ensure env var is not set
            import os

            os.environ.pop("ALERT_CHANNEL", None)
            channel = get_alert_channel()
        assert channel == AlertChannel.LOG

    def test_get_alert_channel_reads_env_var(self) -> None:
        with patch.dict("os.environ", {"ALERT_CHANNEL": "slack"}):
            channel = get_alert_channel()
        assert channel == AlertChannel.SLACK

    def test_get_alert_channel_fallback_on_invalid(self) -> None:
        with patch.dict("os.environ", {"ALERT_CHANNEL": "pigeonpost"}):
            channel = get_alert_channel()
        assert channel == AlertChannel.LOG


# ---------------------------------------------------------------------------
# send_alert — EMAIL channel (SMTP mocked)
# ---------------------------------------------------------------------------


class TestSendAlertEmailChannel:
    def test_email_falls_back_to_log_when_env_missing(self) -> None:
        buf = io.StringIO()
        with patch.dict("os.environ", {}, clear=False):
            import os

            for key in ("SMTP_HOST", "ALERT_EMAIL_FROM", "ALERT_EMAIL_TO"):
                os.environ.pop(key, None)
            with patch.object(sys, "stderr", buf):
                send_alert("email_check", "detail", AlertChannel.EMAIL)

        # Should still produce log output as fallback
        assert buf.getvalue().strip()


# ---------------------------------------------------------------------------
# send_alert — SLACK channel (urllib mocked)
# ---------------------------------------------------------------------------


class TestSendAlertSlackChannel:
    def test_slack_falls_back_to_log_when_no_webhook(self) -> None:
        buf = io.StringIO()
        with patch.dict("os.environ", {}, clear=False):
            import os

            os.environ.pop("SLACK_WEBHOOK_URL", None)
            with patch.object(sys, "stderr", buf):
                send_alert("slack_check", "detail", AlertChannel.SLACK)

        assert buf.getvalue().strip()

    def test_slack_posts_to_webhook(self) -> None:
        import urllib.request

        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with (
            patch.dict("os.environ", {"SLACK_WEBHOOK_URL": "https://hooks.slack.com/test"}),
            patch.object(urllib.request, "urlopen", return_value=mock_resp),
            patch.object(urllib.request, "Request") as mock_req_cls,
        ):
            send_alert("slack_ok", "all good", AlertChannel.SLACK)
            mock_req_cls.assert_called_once()
            call_kwargs = mock_req_cls.call_args
            body = call_kwargs[1].get("data") or call_kwargs[0][1]
            payload = json.loads(body.decode())
            assert "slack_ok" in payload["text"]
