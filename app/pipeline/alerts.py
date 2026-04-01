"""Pipeline alerting module.

Supports three alert channels controlled by the ``ALERT_CHANNEL`` env var:
  log   (default) — structured JSON written to stderr
  email           — SMTP email using SMTP_HOST / SMTP_PORT / ALERT_EMAIL_* vars
  slack           — HTTP POST to SLACK_WEBHOOK_URL

All channels fail gracefully: if required env vars are missing, the alert is
downgraded to a ``log`` channel write and a warning is emitted.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import UTC, datetime
from enum import StrEnum

logger = logging.getLogger(__name__)


class AlertChannel(StrEnum):
    LOG = "log"
    EMAIL = "email"
    SLACK = "slack"


def get_alert_channel() -> AlertChannel:
    """Return the configured alert channel (default: ``log``)."""
    raw = os.environ.get("ALERT_CHANNEL", "log").lower().strip()
    try:
        return AlertChannel(raw)
    except ValueError:
        logger.warning("Unknown ALERT_CHANNEL=%r — falling back to 'log'.", raw)
        return AlertChannel.LOG


def _send_log_alert(check_name: str, detail: str) -> None:
    payload = json.dumps(
        {
            "alert": check_name,
            "detail": detail,
            "timestamp": datetime.now(tz=UTC).isoformat(),
        }
    )
    sys.stderr.write(payload + "\n")
    sys.stderr.flush()


def _send_email_alert(check_name: str, detail: str) -> None:
    import smtplib  # noqa: PLC0415
    from email.message import EmailMessage  # noqa: PLC0415

    smtp_host = os.environ.get("SMTP_HOST")
    smtp_port_str = os.environ.get("SMTP_PORT", "587")
    from_addr = os.environ.get("ALERT_EMAIL_FROM")
    to_addr = os.environ.get("ALERT_EMAIL_TO")

    if not all([smtp_host, from_addr, to_addr]):
        logger.warning(
            "Email alert misconfigured (missing SMTP_HOST/ALERT_EMAIL_FROM/ALERT_EMAIL_TO). "
            "Falling back to log channel."
        )
        _send_log_alert(check_name, detail)
        return

    # Narrow types post-guard for mypy
    assert smtp_host is not None
    assert from_addr is not None
    assert to_addr is not None

    try:
        smtp_port = int(smtp_port_str)
        msg = EmailMessage()
        msg["Subject"] = f"[WEM Pipeline Alert] {check_name}"
        msg["From"] = from_addr
        msg["To"] = to_addr
        msg.set_content(f"Alert: {check_name}\n\n{detail}")

        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.send_message(msg)

        logger.info("Email alert sent for check '%s'.", check_name)
    except Exception:  # noqa: BLE001
        logger.exception("Failed to send email alert — falling back to log.")
        _send_log_alert(check_name, detail)


def _send_slack_alert(check_name: str, detail: str) -> None:
    import urllib.request  # noqa: PLC0415

    webhook_url = os.environ.get("SLACK_WEBHOOK_URL")
    if not webhook_url:
        logger.warning(
            "SLACK_WEBHOOK_URL not configured. Falling back to log channel."
        )
        _send_log_alert(check_name, detail)
        return

    try:
        body = json.dumps({"text": f"[ALERT] {check_name}: {detail}"}).encode()
        req = urllib.request.Request(
            webhook_url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
            if resp.status not in (200, 204):
                raise RuntimeError(f"Slack responded with HTTP {resp.status}")
        logger.info("Slack alert sent for check '%s'.", check_name)
    except Exception:  # noqa: BLE001
        logger.exception("Failed to send Slack alert — falling back to log.")
        _send_log_alert(check_name, detail)


def send_alert(
    check_name: str,
    detail: str,
    channel: AlertChannel | None = None,
) -> None:
    """Send a pipeline alert via the configured channel.

    Args:
        check_name: Name of the failing health check.
        detail: Human-readable description of the failure.
        channel: Override the channel; if ``None`` uses ``get_alert_channel()``.
    """
    resolved = channel if channel is not None else get_alert_channel()

    if resolved == AlertChannel.EMAIL:
        _send_email_alert(check_name, detail)
    elif resolved == AlertChannel.SLACK:
        _send_slack_alert(check_name, detail)
    else:
        _send_log_alert(check_name, detail)
