"""Unit tests for PPA and offtake contract modelling."""

from __future__ import annotations

import pandas as pd
import pytest

from app.financial.ppa import PPAContract, PPAResult, calculate_ppa_revenue


def _make_dispatch_df(dispatch_mwh: list[float], mcp_aud_mwh: list[float]) -> pd.DataFrame:
    return pd.DataFrame({"dispatch_mwh": dispatch_mwh, "mcp_aud_mwh": mcp_aud_mwh})


class TestFixedPricePPA:
    def test_basic_fixed_price(self) -> None:
        """Fixed price: all dispatch at contract price, no merchant."""
        df = _make_dispatch_df([10.0, 10.0, 10.0], [50.0, 60.0, 70.0])
        contract = PPAContract(contract_type="fixed_price", price_per_mwh=80.0)
        result = calculate_ppa_revenue(df, contract)

        assert isinstance(result, PPAResult)
        assert result.contracted_mwh == pytest.approx(30.0)
        assert result.merchant_mwh == pytest.approx(0.0)
        assert result.contracted_revenue == pytest.approx(30.0 * 80.0)
        assert result.merchant_revenue == pytest.approx(0.0)
        assert result.total_revenue == pytest.approx(30.0 * 80.0)

    def test_fixed_price_with_annual_cap(self) -> None:
        """Volume cap splits contracted and merchant dispatch."""
        df = _make_dispatch_df([20.0, 20.0, 20.0], [50.0, 50.0, 50.0])
        contract = PPAContract(
            contract_type="fixed_price", price_per_mwh=100.0, annual_cap_mwh=30.0
        )
        result = calculate_ppa_revenue(df, contract)

        # 30 MWh contracted at $100, 30 MWh merchant at $50
        assert result.contracted_mwh == pytest.approx(30.0)
        assert result.merchant_mwh == pytest.approx(30.0)
        assert result.contracted_revenue == pytest.approx(30.0 * 100.0)
        assert result.merchant_revenue == pytest.approx(30.0 * 50.0)
        assert result.total_revenue == pytest.approx(3000.0 + 1500.0)


class TestFloorSharePPA:
    def test_floor_share_all_above_floor(self) -> None:
        """MCP above floor: revenue includes upside share."""
        df = _make_dispatch_df([10.0], [100.0])  # MCP = 100, floor = 60, share = 0.5
        contract = PPAContract(contract_type="floor_share", price_per_mwh=60.0, share_pct=0.5)
        result = calculate_ppa_revenue(df, contract)

        # effective_price = 60 + 0.5 * (100 - 60) = 60 + 20 = 80
        assert result.contracted_revenue == pytest.approx(10.0 * 80.0)
        assert result.merchant_mwh == pytest.approx(0.0)
        assert result.total_revenue == pytest.approx(800.0)

    def test_floor_share_below_floor(self) -> None:
        """MCP below floor: buyer receives floor price."""
        df = _make_dispatch_df([10.0], [30.0])  # MCP = 30, floor = 60
        contract = PPAContract(contract_type="floor_share", price_per_mwh=60.0, share_pct=0.5)
        result = calculate_ppa_revenue(df, contract)

        # effective_price = max(60, 30) = 60 (no upside)
        assert result.contracted_revenue == pytest.approx(10.0 * 60.0)
        assert result.total_revenue == pytest.approx(600.0)

    def test_floor_share_mixed(self) -> None:
        """Two intervals: one above and one below floor."""
        df = _make_dispatch_df([5.0, 5.0], [80.0, 40.0])
        contract = PPAContract(contract_type="floor_share", price_per_mwh=60.0, share_pct=0.5)
        result = calculate_ppa_revenue(df, contract)

        # Interval 1: 5 × (60 + 0.5×20) = 5 × 70 = 350
        # Interval 2: 5 × 60 = 300 (below floor)
        assert result.contracted_revenue == pytest.approx(650.0)


class TestIndexedPPA:
    def test_indexed_price(self) -> None:
        """Indexed price scales base price by CPI factor."""
        df = _make_dispatch_df([10.0, 10.0], [50.0, 50.0])
        contract = PPAContract(contract_type="indexed", price_per_mwh=80.0, cpi_index=1.05)
        result = calculate_ppa_revenue(df, contract)

        effective_price = 80.0 * 1.05  # = 84.0
        assert result.contracted_revenue == pytest.approx(20.0 * effective_price)
        assert result.total_revenue == pytest.approx(20.0 * effective_price)

    def test_indexed_with_cap(self) -> None:
        """Indexed price with annual cap splits correctly."""
        df = _make_dispatch_df([10.0, 10.0], [50.0, 50.0])
        contract = PPAContract(
            contract_type="indexed", price_per_mwh=80.0, cpi_index=1.1, annual_cap_mwh=10.0
        )
        result = calculate_ppa_revenue(df, contract)

        assert result.contracted_mwh == pytest.approx(10.0)
        assert result.merchant_mwh == pytest.approx(10.0)
        assert result.contracted_revenue == pytest.approx(10.0 * 80.0 * 1.1)
        assert result.merchant_revenue == pytest.approx(10.0 * 50.0)


class TestEdgeCases:
    def test_missing_column_raises(self) -> None:
        df = pd.DataFrame({"dispatch_mwh": [10.0]})
        contract = PPAContract(contract_type="fixed_price", price_per_mwh=80.0)
        with pytest.raises(ValueError, match="mcp_aud_mwh"):
            calculate_ppa_revenue(df, contract)

    def test_zero_dispatch(self) -> None:
        df = _make_dispatch_df([0.0, 0.0], [50.0, 60.0])
        contract = PPAContract(contract_type="fixed_price", price_per_mwh=80.0)
        result = calculate_ppa_revenue(df, contract)
        assert result.total_revenue == pytest.approx(0.0)
