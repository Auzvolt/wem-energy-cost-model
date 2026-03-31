"""Tests for AEMO WA API endpoint mapping — issues #2, #3, #4.

Verifies:
- URL builders produce correctly-structured endpoint URLs
- Fixture CSV files match the documented schema
- All FCESS products are covered
"""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

import pytest

from app.pipeline.wholesale_price_connector import (
    FCESS_PRODUCTS,
    balancing_summary_url,
    fcess_price_url,
)

FIXTURES = Path(__file__).parent / "fixtures" / "interval_data"

# ---------------------------------------------------------------------------
# Issue #2 — Wholesale energy price API mapping
# ---------------------------------------------------------------------------


class TestWholesalePriceAPI:
    """Verify energy balancing summary URL structure and fixture schema."""

    def test_balancing_summary_url_structure(self) -> None:
        """URL must follow the documented pattern."""
        url = balancing_summary_url(date(2024, 1, 15))
        assert "data.wa.aemo.com.au" in url
        assert "balancing-summary" in url
        assert "20240115" in url
        assert url.endswith(".csv")

    def test_balancing_summary_fixture_schema(self) -> None:
        """Fixture CSV must contain required columns."""
        required_columns = {
            "TradingDate",
            "TradingInterval",
            "IntervalStart",
            "BalancingPrice",
        }
        fixture = FIXTURES / "BalancingSummary_20240115.csv"
        assert fixture.exists(), f"Fixture missing: {fixture}"
        with fixture.open() as f:
            reader = csv.DictReader(f)
            assert reader.fieldnames is not None
            cols = set(reader.fieldnames)
            missing = required_columns - cols
            assert not missing, f"Missing columns: {missing}"
            rows = list(reader)
            assert len(rows) > 0, "Fixture has no data rows"

    def test_balancing_summary_price_values_are_numeric(self) -> None:
        """BalancingPrice column must contain parseable floats."""
        fixture = FIXTURES / "BalancingSummary_20240115.csv"
        with fixture.open() as f:
            reader = csv.DictReader(f)
            for row in reader:
                price = float(row["BalancingPrice"])
                assert -1000.0 <= price <= 17500.0, f"Price out of WEM bounds: {price}"

    def test_trading_interval_range(self) -> None:
        """5-min intervals: 1–288 per trading day."""
        fixture = FIXTURES / "BalancingSummary_20240115.csv"
        with fixture.open() as f:
            reader = csv.DictReader(f)
            for row in reader:
                interval = int(row["TradingInterval"])
                assert 1 <= interval <= 288, f"Invalid interval: {interval}"


# ---------------------------------------------------------------------------
# Issue #3 — FCESS product API mapping
# ---------------------------------------------------------------------------


class TestFCESSAPI:
    """Verify FCESS product endpoint URLs and fixture schemas."""

    EXPECTED_PRODUCTS = frozenset(
        {
            "REGULATION_RAISE",
            "REGULATION_LOWER",
            "CONTINGENCY_RESERVE_RAISE",
            "CONTINGENCY_RESERVE_LOWER",
            "ROCOF_CONTROL_SERVICE",
        }
    )

    def test_all_five_products_defined(self) -> None:
        """FCESS_PRODUCTS must contain all 5 post-reform products."""
        assert set(FCESS_PRODUCTS) == self.EXPECTED_PRODUCTS

    @pytest.mark.parametrize("product", list(EXPECTED_PRODUCTS))
    def test_fcess_url_structure(self, product: str) -> None:
        """Each product URL must follow the documented pattern."""
        url = fcess_price_url(date(2024, 1, 15), product)
        assert "data.wa.aemo.com.au" in url
        assert "fcess-prices" in url
        assert product in url
        assert "20240115" in url
        assert url.endswith(".csv")

    @pytest.mark.parametrize("product", list(EXPECTED_PRODUCTS))
    def test_fcess_fixture_exists(self, product: str) -> None:
        """Fixture file must exist for each FCESS product."""
        fixture = FIXTURES / f"FCESSPrice_{product}_20240115.csv"
        assert fixture.exists(), f"Missing fixture: {fixture}"

    @pytest.mark.parametrize("product", list(EXPECTED_PRODUCTS))
    def test_fcess_fixture_schema(self, product: str) -> None:
        """Each FCESS fixture must contain required clearing price columns."""
        required_columns = {
            "TradingDate",
            "TradingInterval",
            "IntervalStart",
            "ClearingPrice",
            "AvailabilityPrice",
        }
        fixture = FIXTURES / f"FCESSPrice_{product}_20240115.csv"
        with fixture.open() as f:
            reader = csv.DictReader(f)
            assert reader.fieldnames is not None
            cols = set(reader.fieldnames)
            missing = required_columns - cols
            assert not missing, f"Product {product} missing columns: {missing}"
            rows = list(reader)
            assert len(rows) > 0

    @pytest.mark.parametrize("product", list(EXPECTED_PRODUCTS))
    def test_fcess_prices_non_negative(self, product: str) -> None:
        """FCESS clearing prices must be non-negative."""
        fixture = FIXTURES / f"FCESSPrice_{product}_20240115.csv"
        with fixture.open() as f:
            reader = csv.DictReader(f)
            for row in reader:
                clearing = float(row["ClearingPrice"])
                availability = float(row["AvailabilityPrice"])
                assert clearing >= 0.0, f"{product} negative clearing price: {clearing}"
                assert availability >= 0.0, f"{product} negative availability: {availability}"

    def test_settlement_interval_aligned_with_energy(self) -> None:
        """FCESS intervals must align 1:1 with energy intervals."""
        energy_fixture = FIXTURES / "BalancingSummary_20240115.csv"
        fcess_fixture = FIXTURES / "FCESSPrice_REGULATION_RAISE_20240115.csv"
        with energy_fixture.open() as f:
            energy_intervals = {row["TradingInterval"] for row in csv.DictReader(f)}
        with fcess_fixture.open() as f:
            fcess_intervals = {row["TradingInterval"] for row in csv.DictReader(f)}
        assert energy_intervals == fcess_intervals, "Interval alignment mismatch"


# ---------------------------------------------------------------------------
# Issue #4 — Capacity mechanism API mapping
# ---------------------------------------------------------------------------


class TestCapacityMechanismAPI:
    """Verify RCM capacity credit price fixture schema."""

    def test_capacity_credit_fixture_exists(self) -> None:
        """Capacity credit price fixture must exist."""
        fixture = FIXTURES / "CapacityCreditPrices_2024.csv"
        assert fixture.exists(), f"Missing fixture: {fixture}"

    def test_capacity_credit_fixture_schema(self) -> None:
        """RCM fixture must contain required columns."""
        required_columns = {
            "CapacityYear",
            "CapacityPrice",
            "ReserveCapacityTarget",
            "TotalCreditsIssued",
        }
        fixture = FIXTURES / "CapacityCreditPrices_2024.csv"
        with fixture.open() as f:
            reader = csv.DictReader(f)
            assert reader.fieldnames is not None
            cols = set(reader.fieldnames)
            missing = required_columns - cols
            assert not missing, f"Missing columns: {missing}"
            rows = list(reader)
            assert len(rows) > 0

    def test_capacity_price_positive(self) -> None:
        """Capacity credit price must be positive (AUD/MW/year)."""
        fixture = FIXTURES / "CapacityCreditPrices_2024.csv"
        with fixture.open() as f:
            reader = csv.DictReader(f)
            for row in reader:
                price = float(row["CapacityPrice"])
                assert price > 0.0, f"Non-positive capacity price: {price}"

    def test_capacity_year_range(self) -> None:
        """Capacity year must be a plausible WEM year."""
        fixture = FIXTURES / "CapacityCreditPrices_2024.csv"
        with fixture.open() as f:
            reader = csv.DictReader(f)
            for row in reader:
                year = int(row["CapacityYear"])
                assert 2006 <= year <= 2100, f"Implausible capacity year: {year}"
