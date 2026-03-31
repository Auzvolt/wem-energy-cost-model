"""Pyomo LP/MILP co-optimisation model — placeholder scaffold."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class WEMOptimisationModel:
    """Pyomo-based co-optimisation model for WEM market participation.

    Covers: wholesale energy, FCESS (5 products), Reserve Capacity Mechanism.

    This is a scaffold — full implementation follows Issues #18–#28.
    """

    def __init__(self, solver: str = "cbc") -> None:
        """Initialise the model.

        Args:
            solver: Pyomo solver name. Defaults to 'cbc'. Override via
                    PYOMO_SOLVER env var to use 'gurobi' or 'glpk'.
        """
        self.solver = solver
        self._model: Any = None  # pyomo.environ.ConcreteModel placeholder

    def build(self, inputs: dict[str, Any]) -> None:
        """Build the Pyomo model from input data.

        Args:
            inputs: Dictionary containing time series data and asset parameters.

        TODO: implement once engine scaffold (Issue #18) is complete.
        """
        raise NotImplementedError("Model build not yet implemented.")

    def solve(self) -> dict[str, Any]:
        """Invoke the solver and return extracted results.

        Returns:
            Dictionary with status, objective value, and decision variable traces.

        TODO: implement once engine scaffold (Issue #18) is complete.
        """
        raise NotImplementedError("Model solve not yet implemented.")
