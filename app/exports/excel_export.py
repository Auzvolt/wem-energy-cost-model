"""Excel workbook export — placeholder scaffold."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class ExcelExporter:
    """Generates multi-sheet Excel workbooks from simulation results.

    TODO: implement once report design (Issue #43) is complete.
    """

    def export(self, results: dict[str, Any], output_path: str) -> str:
        """Generate an Excel workbook and write it to output_path.

        Args:
            results: Simulation and financial results dictionary.
            output_path: File path for the generated .xlsx file.

        Returns:
            Absolute path to the generated file.
        """
        raise NotImplementedError("Excel export not yet implemented.")
