"""Result Reader — watches MT5 signals.csv for EA execution results.

The EA updates the status column in signals.csv from PENDING to EXECUTED/FAILED.
This module watches for those changes and reports them back to the Aurora API.
"""

import asyncio
import csv
import logging
from pathlib import Path
from typing import AsyncIterator

from models import ExecutionResult

logger = logging.getLogger("aurora-bridge")


class ResultReader:
    """Watches signals.csv for execution results from the MT5 EA."""

    def __init__(self, mt5_files_path: str, signal_filename: str = "signals.csv"):
        self.signal_file = Path(mt5_files_path) / signal_filename
        self.reported_ids: set[str] = set()
        self._running = False

    async def watch(self, interval: float = 2.0) -> AsyncIterator[ExecutionResult]:
        """Poll signals.csv for status changes. Yields ExecutionResults."""
        self._running = True
        logger.info(f"Watching for EA results in {self.signal_file}")

        while self._running:
            try:
                if self.signal_file.exists():
                    results = self._read_results()
                    for result in results:
                        if result.signal_id not in self.reported_ids:
                            self.reported_ids.add(result.signal_id)
                            yield result
            except Exception as e:
                logger.error(f"Error reading results: {e}")

            await asyncio.sleep(interval)

    def _read_results(self) -> list[ExecutionResult]:
        """Read all non-pending signals from the CSV."""
        results = []
        try:
            with open(self.signal_file, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    status_raw = (row.get("status") or "").strip().upper()
                    signal_id = (row.get("signal_id") or "").strip()

                    if not signal_id or status_raw == "PENDING":
                        continue

                    # Map EA statuses to API statuses
                    if status_raw == "EXECUTED":
                        api_status = "executed"
                    else:
                        api_status = "failed"

                    results.append(ExecutionResult(
                        signal_id=signal_id,
                        status=api_status,
                        error_message=status_raw if api_status == "failed" else None,
                    ))
        except Exception as e:
            logger.error(f"Failed to read results CSV: {e}")

        return results

    def stop(self):
        self._running = False
