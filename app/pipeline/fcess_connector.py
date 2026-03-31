"""AEMO FCESS (Frequency Control and System Services) price data connectors.

Fetches all 5 FCESS product prices from the AEMO WA balancing market API
and persists them to the ``fcess_prices`` PostgreSQL table.

Products:
  - REG_RAISE   — Regulation Raise
  - REG_LOWER   — Regulation Lower
  - CONT_RAISE  — Contingency Raise
  - CONT_LOWER  — Contingency Lower
  - ROCOF       — Rate-of-Change-of-Frequency Control

Environment variables:
  AEMO_API_BASE_URL — base URL for AEMO WA data portal
  AEMO_API_KEY      — optional API key header value
"""

from __future__ import annotations

import contextlib
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Column, DateTime, Float, Integer, String, UniqueConstraint, text
from sqlalchemy.orm import Session

from app.config import AEMO_API_BASE_URL, AEMO_API_KEY
from app.db.models import Base

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Product catalogue
# ---------------------------------------------------------------------------

#: Map from canonical product code to a human-readable label and URL suffix.
FCESS_PRODUCTS: dict[str, dict[str, str]] = {
    "REG_RAISE": {
        "label": "Regulation Raise",
        "path": "/api/v1/facilities/opcap/regulation-raise",
    },
    "REG_LOWER": {
        "label": "Regulation Lower",
        "path": "/api/v1/facilities/opcap/regulation-lower",
    },
    "CONT_RAISE": {
        "label": "Contingency Raise",
        "path": "/api/v1/facilities/opcap/contingency-raise",
    },
    "CONT_LOWER": {
        "label": "Contingency Lower",
        "path": "/api/v1/facilities/opcap/contingency-lower",
    },
    "ROCOF": {
        "label": "RoCoF Control",
        "path": "/api/v1/facilities/opcap/rocof-control",
    },
}

_VALID_PRODUCTS = frozenset(FCESS_PRODUCTS.keys())

# ---------------------------------------------------------------------------
# ORM model
# ---------------------------------------------------------------------------


class FcessPrice(Base):
    """Persisted FCESS clearing price record."""

    __tablename__ = "fcess_prices"
    __table_args__ = (
        UniqueConstraint("product", "interval_start_utc", name="uq_fcess_product_interval"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    product = Column(String(32), nullable=False, index=True)
    interval_start_utc = Column(DateTime(timezone=True), nullable=False, index=True)
    price_aud_mwh = Column(Float, nullable=False)
    source_url = Column(String(512), nullable=True)
    fetched_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    def __repr__(self) -> str:
        return (
            f"<FcessPrice product={self.product!r} "
            f"interval={self.interval_start_utc!r} "
            f"price={self.price_aud_mwh}>"
        )


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

_DEFAULT_TIMEOUT_S = 30
_PAGE_DAYS = 7  # request window per API call


def _build_headers() -> dict[str, str]:
    headers: dict[str, str] = {"Accept": "application/json"}
    if AEMO_API_KEY:
        headers["X-API-Key"] = AEMO_API_KEY
    return headers


def _fetch_raw(
    session_http: Any,
    product: str,
    from_dt: datetime,
    to_dt: datetime,
) -> list[dict[str, Any]]:
    """Fetch raw JSON price rows for one product over a time window.

    Args:
        session_http: ``httpx.Client`` (or compatible sync HTTP client).
        product: One of the keys in ``FCESS_PRODUCTS``.
        from_dt: Window start (UTC-aware).
        to_dt: Window end (UTC-aware).

    Returns:
        List of raw row dicts from the API response ``data`` array.
    """
    if product not in _VALID_PRODUCTS:
        raise ValueError(f"Unknown FCESS product: {product!r}. Valid: {sorted(_VALID_PRODUCTS)}")

    path = FCESS_PRODUCTS[product]["path"]
    url = f"{AEMO_API_BASE_URL.rstrip('/')}{path}"
    params = {
        "from": from_dt.strftime("%Y-%m-%dT%H:%M:%S"),
        "to": to_dt.strftime("%Y-%m-%dT%H:%M:%S"),
    }

    response = session_http.get(
        url, params=params, headers=_build_headers(), timeout=_DEFAULT_TIMEOUT_S
    )
    response.raise_for_status()

    payload = response.json()
    if isinstance(payload, dict):
        return payload.get("data", []) or []
    if isinstance(payload, list):
        return payload
    return []


def _row_to_record(row: dict[str, Any], product: str, source_url: str) -> FcessPrice | None:
    """Convert a raw API row dict to a ``FcessPrice`` ORM instance.

    Tolerates varying column names across AEMO API versions.
    Returns ``None`` if mandatory fields cannot be parsed.
    """
    _AWST_OFFSET = 8 * 3600  # seconds

    # Timestamp — use explicit None checks so falsy values (e.g. "0") are preserved
    ts_raw = None
    for _ts_key in ("DISPATCH_INTERVAL_START", "INTERVAL_START", "TRADING_DATE", "interval_start"):
        _v = row.get(_ts_key)
        if _v is not None:
            ts_raw = _v
            break
    if ts_raw is None:
        return None

    ts_str = str(ts_raw).strip()
    ts_utc: datetime | None = None
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%Y-%m-%d",
    ):
        try:
            ts_awst = datetime.strptime(ts_str, fmt)
            ts_utc = ts_awst.replace(tzinfo=UTC) - timedelta(seconds=_AWST_OFFSET)
            break
        except ValueError:
            continue

    if ts_utc is None:
        log.debug("Could not parse FCESS timestamp: %r", ts_raw)
        return None

    # Price — use explicit None checks so 0.0 and other falsy numeric values are preserved
    price_raw = None
    for _p_key in ("MARKET_CLEARING_PRICE", "MCP", "CLEARING_PRICE", "PRICE", "price_aud_mwh"):
        _v = row.get(_p_key)
        if _v is not None:
            price_raw = _v
            break
    try:
        price = float(price_raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None

    return FcessPrice(
        product=product,
        interval_start_utc=ts_utc,
        price_aud_mwh=price,
        source_url=source_url,
        fetched_at=datetime.now(UTC),
    )


# ---------------------------------------------------------------------------
# Public fetch API
# ---------------------------------------------------------------------------


def fetch_fcess_prices(
    product: str,
    from_dt: datetime,
    to_dt: datetime,
    db: Session,
    *,
    http_client: Any | None = None,
) -> list[FcessPrice]:
    """Fetch FCESS prices for *product* in ``[from_dt, to_dt)`` and persist them.

    Supports incremental fetch: if records already exist in the DB for this
    product, ``from_dt`` is advanced to ``max(interval_start_utc) + 1 interval``.

    Args:
        product: FCESS product code (key of ``FCESS_PRODUCTS``).
        from_dt: Earliest interval to fetch (UTC-aware).
        to_dt: Latest interval to fetch (UTC-aware).
        db: SQLAlchemy ``Session``.
        http_client: Optional pre-built ``httpx.Client``; created internally if not provided.

    Returns:
        List of newly persisted ``FcessPrice`` records.
    """
    if product not in _VALID_PRODUCTS:
        raise ValueError(f"Unknown FCESS product: {product!r}")

    # Incremental: advance from_dt to latest stored record + 5 min
    latest_sql = text("SELECT MAX(interval_start_utc) FROM fcess_prices WHERE product = :product")
    row = db.execute(latest_sql, {"product": product}).fetchone()
    if row and row[0] is not None:
        # SQLite returns datetime columns as strings; PostgreSQL returns datetime objects
        _raw = row[0]
        if isinstance(_raw, str):
            latest_stored: datetime = datetime.fromisoformat(_raw.replace("Z", "+00:00"))
        else:
            latest_stored = _raw
        if not latest_stored.tzinfo:
            latest_stored = latest_stored.replace(tzinfo=UTC)
        incremental_from = latest_stored + timedelta(minutes=5)
        if incremental_from > from_dt:
            from_dt = incremental_from
            log.debug(
                "FCESS %s: incremental fetch from %s (latest stored: %s)",
                product,
                from_dt,
                latest_stored,
            )

    if from_dt >= to_dt:
        log.info("FCESS %s: nothing to fetch (from_dt >= to_dt)", product)
        return []

    # Build HTTP client if not injected
    _owns_client = http_client is None
    if http_client is None:
        try:
            import httpx

            http_client = httpx.Client()
        except ImportError as exc:
            raise RuntimeError("httpx is required for FCESS price fetching") from exc

    persisted: list[FcessPrice] = []
    path = FCESS_PRODUCTS[product]["path"]
    source_url = f"{AEMO_API_BASE_URL.rstrip('/')}{path}"

    try:
        # Paginate in _PAGE_DAYS-day windows to avoid large payloads
        cursor = from_dt
        while cursor < to_dt:
            window_end = min(cursor + timedelta(days=_PAGE_DAYS), to_dt)
            try:
                rows = _fetch_raw(http_client, product, cursor, window_end)
            except Exception as exc:
                log.warning(
                    "FCESS %s: fetch failed for window %s–%s: %s",
                    product,
                    cursor,
                    window_end,
                    exc,
                )
                break

            for raw in rows:
                record = _row_to_record(raw, product, source_url)
                if record is None:
                    continue
                # Upsert: skip if already stored
                exists = (
                    db.query(FcessPrice)
                    .filter_by(
                        product=product,
                        interval_start_utc=record.interval_start_utc,
                    )
                    .first()
                )
                if exists is None:
                    db.add(record)
                    persisted.append(record)

            cursor = window_end

        db.flush()
    finally:
        if _owns_client:
            with contextlib.suppress(Exception):
                http_client.close()

    log.info("FCESS %s: persisted %d new records", product, len(persisted))
    return persisted


def fetch_all_fcess_products(
    from_dt: datetime,
    to_dt: datetime,
    db: Session,
    *,
    http_client: Any | None = None,
) -> dict[str, list[FcessPrice]]:
    """Fetch all 5 FCESS products in sequence.

    Args:
        from_dt: Earliest interval to fetch (UTC-aware).
        to_dt: Latest interval to fetch (UTC-aware).
        db: SQLAlchemy ``Session``.
        http_client: Optional shared ``httpx.Client``.

    Returns:
        Dict mapping product code to list of newly persisted records.
    """
    results: dict[str, list[FcessPrice]] = {}
    for product in FCESS_PRODUCTS:
        results[product] = fetch_fcess_prices(product, from_dt, to_dt, db, http_client=http_client)
    return results
