"""PDF report export — placeholder scaffold."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class PDFExporter:
    """Generates branded PDF reports from simulation results.

    TODO: implement once report design (Issue #43) is complete.
    """

    def export(self, results: dict[str, Any], output_path: str) -> str:
        """Generate a PDF report and write it to output_path.

        Args:
            results: Simulation and financial results dictionary.
            output_path: File path for the generated PDF.

        Returns:
            Absolute path to the generated file.
        """
        raise NotImplementedError("PDF export not yet implemented.")
