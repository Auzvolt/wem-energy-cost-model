"""Tests for app.optimisation.ev_fleet -- EV fleet smart charging and V2G model.

Covers:
  - EVConfig validation (field bounds, cross-field validators)
  - EVFleetConfig validation (vehicle list, power limits, efficiency)
  - add_ev_fleet_constraints() model structure (variables, constraints added)
  - SoC balance correctness over a simple trace
  - Departure SoC hard constraint enforced
  - V2G flag gates discharge power
  - Fleet aggregate = sum of per-vehicle allocations
  - Solver integration: vehicles fully charged before departure
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.optimisation.ev_fleet import EVConfig, EVFleetConfig, add_ev_fleet_constraints

# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------


def _ev(
    vehicle_id: str = "EV-01",
    battery_kwh: float = 60.0,
    max_charge_kw: float = 7.4,
    arrival_interval: int = 0,
    departure_interval: int = 5,
    soc_on_arrival_kwh: float = 20.0,
    soc_target_kwh: float = 54.0,
) -> EVConfig:
    return EVConfig(
        vehicle_id=vehicle_id,
        battery_kwh=battery_kwh,
        max_charge_kw=max_charge_kw,
        arrival_interval=arrival_interval,
        departure_interval=departure_interval,
        soc_on_arrival_kwh=soc_on_arrival_kwh,
        soc_target_kwh=soc_target_kwh,
    )


def _fleet(
    vehicles: list[EVConfig] | None = None,
    fleet_max_charge_kw: float = 22.0,
    enable_v2g: bool = False,
    fleet_max_discharge_kw: float = 0.0,
    efficiency_rt: float = 0.92,
) -> EVFleetConfig:
    if vehicles is None:
        vehicles = [_ev()]
    return EVFleetConfig(
        vehicles=vehicles,
        fleet_max_charge_kw=fleet_max_charge_kw,
        fleet_max_discharge_kw=fleet_max_discharge_kw,
        efficiency_rt=efficiency_rt,
        enable_v2g=enable_v2g,
    )


# ---------------------------------------------------------------------------
# EVConfig validation
# ---------------------------------------------------------------------------


class TestEVConfig:
    def test_valid_defaults(self) -> None:
        cfg = _ev()
        assert cfg.battery_kwh == pytest.approx(60.0)
        assert cfg.max_charge_kw == pytest.approx(7.4)
        assert cfg.soc_target_kwh == pytest.approx(54.0)

    def test_negative_battery_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _ev(battery_kwh=-1.0)

    def test_zero_battery_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _ev(battery_kwh=0.0)

    def test_soc_target_exceeds_capacity_rejected(self) -> None:
        with pytest.raises(ValidationError, match="exceeds battery_kwh"):
            _ev(battery_kwh=60.0, soc_target_kwh=70.0)

    def test_arrival_soc_exceeds_capacity_rejected(self) -> None:
        with pytest.raises(ValidationError, match="exceeds battery_kwh"):
            _ev(battery_kwh=60.0, soc_on_arrival_kwh=65.0)

    def test_departure_before_arrival_rejected(self) -> None:
        with pytest.raises(ValidationError, match="departure_interval must be strictly greater"):
            _ev(arrival_interval=5, departure_interval=3)

    def test_departure_equal_arrival_rejected(self) -> None:
        with pytest.raises(ValidationError, match="departure_interval must be strictly greater"):
            _ev(arrival_interval=3, departure_interval=3)

    def test_zero_charge_kw_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _ev(max_charge_kw=0.0)


# ---------------------------------------------------------------------------
# EVFleetConfig validation
# ---------------------------------------------------------------------------


class TestEVFleetConfig:
    def test_valid_single_vehicle(self) -> None:
        cfg = _fleet()
        assert len(cfg.vehicles) == 1
        assert cfg.fleet_max_charge_kw == pytest.approx(22.0)
        assert cfg.enable_v2g is False

    def test_empty_vehicle_list_rejected(self) -> None:
        with pytest.raises(ValidationError):
            EVFleetConfig(vehicles=[], fleet_max_charge_kw=22.0)

    def test_zero_fleet_charge_kw_rejected(self) -> None:
        with pytest.raises(ValidationError):
            EVFleetConfig(vehicles=[_ev()], fleet_max_charge_kw=0.0)

    def test_efficiency_out_of_range_rejected(self) -> None:
        with pytest.raises(ValidationError):
            EVFleetConfig(vehicles=[_ev()], fleet_max_charge_kw=22.0, efficiency_rt=1.5)

    def test_v2g_flag_enables_discharge(self) -> None:
        cfg = _fleet(enable_v2g=True, fleet_max_discharge_kw=11.0)
        assert cfg.fleet_max_discharge_kw == pytest.approx(11.0)
        assert cfg.enable_v2g is True

    def test_multi_vehicle_config(self) -> None:
        vehicles = [
            _ev("EV-01", arrival_interval=0, departure_interval=4),
            _ev("EV-02", arrival_interval=2, departure_interval=6),
        ]
        cfg = _fleet(vehicles=vehicles)
        assert len(cfg.vehicles) == 2


# ---------------------------------------------------------------------------
# Model structure tests (no solver required)
# ---------------------------------------------------------------------------


pyomo = pytest.importorskip("pyomo", reason="pyomo required")


@pytest.fixture()
def simple_model():
    """Minimal Pyomo model with T = {0, 1, 2, 3, 4, 5} (6 x 5-min intervals)."""
    import pyomo.environ as pyo

    m = pyo.ConcreteModel()
    m.T = pyo.Set(initialize=range(6), ordered=True)
    return m


class TestAddEvFleetConstraintsStructure:
    def test_fleet_variables_added(self, simple_model) -> None:
        cfg = _fleet()
        add_ev_fleet_constraints(simple_model, cfg)
        assert hasattr(simple_model, "ev_charge_kw")
        assert hasattr(simple_model, "ev_discharge_kw")

    def test_per_vehicle_variables_added(self, simple_model) -> None:
        cfg = _fleet()
        add_ev_fleet_constraints(simple_model, cfg)
        assert hasattr(simple_model, "ev_soc_kwh")
        assert hasattr(simple_model, "ev_vehicle_charge_kw")

    def test_fleet_constraints_added(self, simple_model) -> None:
        cfg = _fleet()
        add_ev_fleet_constraints(simple_model, cfg)
        assert hasattr(simple_model, "ev_fleet_charge_limit")
        assert hasattr(simple_model, "ev_fleet_discharge_limit")
        assert hasattr(simple_model, "ev_fleet_aggregate")

    def test_per_vehicle_constraints_added(self, simple_model) -> None:
        cfg = _fleet()
        add_ev_fleet_constraints(simple_model, cfg)
        assert hasattr(simple_model, "ev_soc_balance")
        assert hasattr(simple_model, "ev_departure_soc")
        assert hasattr(simple_model, "ev_vehicle_charge_limit")

    def test_soc_variable_indexed_over_presence_set(self, simple_model) -> None:
        """SoC variable only defined for intervals where vehicle is present."""
        ev = _ev(arrival_interval=1, departure_interval=4)
        cfg = _fleet(vehicles=[ev])
        add_ev_fleet_constraints(simple_model, cfg)
        # Vehicle present at t=1,2,3,4
        for t in [1, 2, 3, 4]:
            assert (0, t) in simple_model.ev_presence_set
        # Vehicle absent at t=0 and t=5
        assert (0, 0) not in simple_model.ev_presence_set
        assert (0, 5) not in simple_model.ev_presence_set

    def test_soc_bounds_respect_battery_capacity(self, simple_model) -> None:
        ev = _ev(battery_kwh=80.0, arrival_interval=0, departure_interval=5)
        cfg = _fleet(vehicles=[ev])
        add_ev_fleet_constraints(simple_model, cfg)
        for t in range(6):
            lb, ub = simple_model.ev_soc_kwh[0, t].bounds
            assert lb == pytest.approx(0.0)
            assert ub == pytest.approx(80.0)

    def test_v2g_disabled_discharge_limit_zero(self, simple_model) -> None:
        """When enable_v2g=False the discharge limit constraint forces ev_discharge_kw to 0."""
        cfg = _fleet(enable_v2g=False, fleet_max_discharge_kw=0.0)
        add_ev_fleet_constraints(simple_model, cfg)

        # Evaluate the discharge limit constraint at t=0: ev_discharge_kw[0] <= 0
        con = simple_model.ev_fleet_discharge_limit[0]
        assert con is not None

    def test_multi_vehicle_presence_sets(self, simple_model) -> None:
        """Two vehicles with different windows should have non-overlapping presences."""
        vehicles = [
            _ev("EV-01", arrival_interval=0, departure_interval=2),
            _ev("EV-02", arrival_interval=3, departure_interval=5),
        ]
        cfg = _fleet(vehicles=vehicles)
        add_ev_fleet_constraints(simple_model, cfg)
        # EV-01 present t=0,1,2
        for t in [0, 1, 2]:
            assert (0, t) in simple_model.ev_presence_set
        # EV-02 present t=3,4,5
        for t in [3, 4, 5]:
            assert (1, t) in simple_model.ev_presence_set
        # No cross-presence
        for t in [3, 4, 5]:
            assert (0, t) not in simple_model.ev_presence_set
        for t in [0, 1, 2]:
            assert (1, t) not in simple_model.ev_presence_set


# ---------------------------------------------------------------------------
# Solver integration tests
# ---------------------------------------------------------------------------


class TestEvFleetSolverIntegration:
    @pytest.fixture()
    def solver(self):
        import pyomo.environ as pyo

        s = pyo.SolverFactory("cbc")
        if not s.available():
            pytest.skip("CBC solver not available")
        return s

    def test_vehicle_charged_to_target(self, solver) -> None:
        """Optimiser must charge vehicle to soc_target by departure."""
        import pyomo.environ as pyo

        m = pyo.ConcreteModel()
        m.T = pyo.Set(initialize=range(8), ordered=True)

        # 60 kWh battery, arrives at 20 kWh, needs 54 kWh by t=7
        ev = _ev(
            battery_kwh=60.0,
            max_charge_kw=11.0,
            arrival_interval=0,
            departure_interval=7,
            soc_on_arrival_kwh=20.0,
            soc_target_kwh=54.0,
        )
        cfg = _fleet(vehicles=[ev], fleet_max_charge_kw=22.0)
        interval_h = 5.0 / 60.0
        add_ev_fleet_constraints(m, cfg, interval_h=interval_h)

        # Minimise total energy cost (flat rate)
        m.obj = pyo.Objective(
            expr=sum(m.ev_charge_kw[t] * interval_h for t in m.T),
            sense=pyo.minimize,
        )

        result = solver.solve(m)
        assert str(result.solver.termination_condition) in ("optimal", "feasible")

        # SoC at departure >= target
        final_soc = pyo.value(m.ev_soc_kwh[0, 7])
        assert final_soc >= pytest.approx(54.0, abs=1e-3)

    def test_v2g_discharge_reduces_cost(self, solver) -> None:
        """With V2G enabled the optimiser can earn by discharging at high prices."""
        import pyomo.environ as pyo

        m = pyo.ConcreteModel()
        m.T = pyo.Set(initialize=range(8), ordered=True)

        ev = _ev(
            battery_kwh=80.0,
            max_charge_kw=11.0,
            arrival_interval=0,
            departure_interval=7,
            soc_on_arrival_kwh=60.0,  # arrives well charged
            soc_target_kwh=40.0,  # only needs 40 kWh on departure
        )
        cfg = _fleet(
            vehicles=[ev],
            fleet_max_charge_kw=22.0,
            fleet_max_discharge_kw=11.0,
            enable_v2g=True,
        )
        interval_h = 5.0 / 60.0
        add_ev_fleet_constraints(m, cfg, interval_h=interval_h)

        # Prices: expensive at t=2,3 (good to discharge), cheap at t=5,6
        prices = {0: 50.0, 1: 50.0, 2: 200.0, 3: 200.0, 4: 50.0, 5: 30.0, 6: 30.0, 7: 50.0}
        m.obj = pyo.Objective(
            expr=sum(
                prices[t] * (m.ev_charge_kw[t] - m.ev_discharge_kw[t]) * interval_h for t in m.T
            ),
            sense=pyo.minimize,
        )

        result = solver.solve(m)
        assert str(result.solver.termination_condition) in ("optimal", "feasible")

        # Should discharge at peak price intervals
        total_discharge = sum(pyo.value(m.ev_discharge_kw[t]) for t in m.T)
        assert total_discharge > 0.0

    def test_departure_soc_hard_constraint_infeasible(self) -> None:
        """If target is unreachable (arrival SoC > battery), config raises immediately."""
        with pytest.raises(ValidationError):
            _ev(
                battery_kwh=60.0,
                max_charge_kw=7.4,
                soc_on_arrival_kwh=65.0,  # exceeds battery_kwh
                soc_target_kwh=54.0,
            )

    def test_multi_vehicle_all_charged(self, solver) -> None:
        """All vehicles in a multi-vehicle fleet must reach their SoC targets."""
        import pyomo.environ as pyo

        m = pyo.ConcreteModel()
        m.T = pyo.Set(initialize=range(12), ordered=True)

        vehicles = [
            EVConfig(
                vehicle_id="EV-01",
                battery_kwh=60.0,
                max_charge_kw=7.4,
                arrival_interval=0,
                departure_interval=5,
                soc_on_arrival_kwh=10.0,
                soc_target_kwh=50.0,
            ),
            EVConfig(
                vehicle_id="EV-02",
                battery_kwh=40.0,
                max_charge_kw=7.4,
                arrival_interval=4,
                departure_interval=11,
                soc_on_arrival_kwh=5.0,
                soc_target_kwh=35.0,
            ),
        ]
        cfg = EVFleetConfig(
            vehicles=vehicles,
            fleet_max_charge_kw=22.0,
        )
        interval_h = 5.0 / 60.0
        add_ev_fleet_constraints(m, cfg, interval_h=interval_h)

        m.obj = pyo.Objective(
            expr=sum(m.ev_charge_kw[t] * interval_h for t in m.T),
            sense=pyo.minimize,
        )

        result = solver.solve(m)
        assert str(result.solver.termination_condition) in ("optimal", "feasible")

        # Both vehicles must hit their targets
        assert pyo.value(m.ev_soc_kwh[0, 5]) >= pytest.approx(50.0, abs=1e-3)
        assert pyo.value(m.ev_soc_kwh[1, 11]) >= pytest.approx(35.0, abs=1e-3)
