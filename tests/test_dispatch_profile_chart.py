"""Tests for dispatch profile chart generation (issue #80)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytest.importorskip("matplotlib", reason="matplotlib not installed")

from tests.validation.gridcog_reference_cases import ALL_CASES  # noqa: E402
from tests.validation.plot_dispatch_profiles import (  # noqa: E402
    N_INTERVALS,
    _scenario_slug,
    generate_dispatch_profile,
)

MIN_FILE_SIZE_BYTES = 1000


class TestScenarioSlug:
    def test_slug_is_filename_safe(self) -> None:
        for case in ALL_CASES:
            slug = _scenario_slug(case.name)
            assert re.match(r"^[\w-]+$", slug), f"Slug not filename-safe: {slug!r}"

    def test_slug_is_nonempty(self) -> None:
        for case in ALL_CASES:
            assert _scenario_slug(case.name)


class TestGenerateDispatchProfile:
    def test_returns_all_layers(self) -> None:
        case = ALL_CASES[0]
        profiles = generate_dispatch_profile(case)
        assert set(profiles.keys()) == {
            "solar",
            "bess_charge",
            "bess_discharge",
            "grid_import",
            "grid_export",
        }

    def test_interval_count(self) -> None:
        case = ALL_CASES[0]
        profiles = generate_dispatch_profile(case)
        for key, arr in profiles.items():
            assert len(arr) == N_INTERVALS, (
                f"{key} has {len(arr)} intervals, expected {N_INTERVALS}"
            )

    def test_no_solar_for_case_a(self) -> None:
        case_a = ALL_CASES[0]
        assert case_a.solar_kwp == 0.0
        profiles = generate_dispatch_profile(case_a)
        assert profiles["solar"].max() == 0.0

    def test_solar_present_for_case_b(self) -> None:
        case_b = ALL_CASES[1]
        assert case_b.solar_kwp > 0
        profiles = generate_dispatch_profile(case_b)
        assert profiles["solar"].max() > 0

    def test_bess_charge_is_nonpositive(self) -> None:
        for case in ALL_CASES:
            profiles = generate_dispatch_profile(case)
            assert (profiles["bess_charge"] <= 0).all(), "Charge values must be ≤ 0"

    def test_bess_discharge_is_nonnegative(self) -> None:
        for case in ALL_CASES:
            profiles = generate_dispatch_profile(case)
            assert (profiles["bess_discharge"] >= 0).all()

    def test_grid_import_is_nonnegative(self) -> None:
        for case in ALL_CASES:
            profiles = generate_dispatch_profile(case)
            assert (profiles["grid_import"] >= 0).all()

    def test_grid_export_is_nonnegative(self) -> None:
        for case in ALL_CASES:
            profiles = generate_dispatch_profile(case)
            assert (profiles["grid_export"] >= 0).all()


class TestChartGeneration:
    def test_png_files_created_and_non_empty(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Run main() and assert PNG files are created and non-empty."""
        import tests.validation.plot_dispatch_profiles as pdp

        monkeypatch.setattr(pdp, "OUTPUT_DIR", tmp_path)
        pdp.main()

        for case in ALL_CASES:
            slug = _scenario_slug(case.name)
            png = tmp_path / f"dispatch_profile_{slug}.png"
            assert png.exists(), f"PNG not found: {png}"
            assert png.stat().st_size >= MIN_FILE_SIZE_BYTES, (
                f"PNG too small ({png.stat().st_size} bytes): {png}"
            )

    def test_two_charts_generated(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import tests.validation.plot_dispatch_profiles as pdp

        monkeypatch.setattr(pdp, "OUTPUT_DIR", tmp_path)
        pdp.main()

        pngs = list(tmp_path.glob("dispatch_profile_*.png"))
        assert len(pngs) == len(ALL_CASES), f"Expected {len(ALL_CASES)} PNGs, got {len(pngs)}"
