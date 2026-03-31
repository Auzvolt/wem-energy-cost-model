"""pytest configuration and shared fixtures."""

import pytest


@pytest.fixture
def sample_project_data() -> dict:
    """Minimal project data dict for use in tests."""
    return {
        "name": "Test Project",
        "description": "A test WEM project",
        "lifetime_years": 20,
        "discount_rate": 0.08,
    }
