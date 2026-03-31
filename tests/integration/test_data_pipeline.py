"""Integration tests for the AEMO data pipeline.

These tests are marked with @pytest.mark.integration and are skipped
in standard CI runs. Enable with: pytest -m integration
"""

from __future__ import annotations

import pytest


@pytest.mark.integration
def test_aemo_client_structure():
    """AEMO client module exposes the expected interface."""
    from app.pipeline.aemo_client import AEMOClient

    assert hasattr(AEMOClient, "__init__")
    # Client can be instantiated with a base URL (no actual HTTP call)
    client = AEMOClient(base_url="https://data.wa.aemo.com.au", api_key="")
    assert client is not None


@pytest.mark.integration
def test_wholesale_connector_structure():
    """Wholesale price connector exposes expected interface."""
    from app.pipeline.wholesale_price_connector import WholesalePriceConnector

    assert hasattr(WholesalePriceConnector, "fetch_date_range")
    assert hasattr(WholesalePriceConnector, "fetch_incremental")
    assert hasattr(WholesalePriceConnector, "to_dataframe")


@pytest.mark.integration
def test_fcess_connector_structure():
    """FCESS connector module exposes expected interface."""
    from app.pipeline import fcess_connector

    assert hasattr(fcess_connector, "fetch_fcess_prices")
    assert hasattr(fcess_connector, "fetch_all_fcess_products")
