# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import logging
from typing import Any, Dict, List

from pants.option.subsystem import Subsystem
from pants.reporting.streaming_workunit_handler import StreamingWorkunitContext

logger = logging.getLogger(__name__)


class MetricsReporting(Subsystem):
    """Subsystem to aggregate and display internal Pants metrics."""

    options_scope = "pants-metrics"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._counters: Dict[str, int] = {}

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--report",
            type=bool,
            default=False,
            help="Whether internal Pants metrics should be reported at the end of a run.",
        )

    def handle_workunits(
        self,
        *,
        completed_workunits: List[Dict],
        started_workunits: List[Dict],
        context: StreamingWorkunitContext,
        finished: bool = False,
        **kwargs: Any,
    ) -> None:
        for completed_workunit in completed_workunits:
            for key, value in completed_workunit.get("counters", {}).items():
                if key not in self._counters:
                    self._counters[key] = 0
                self._counters[key] += value

        if finished:
            counters_msg = "Counters:\n"
            for key in sorted(self._counters.keys()):
                counters_msg += f"{key}={self._counters[key]}\n"
            logger.debug(counters_msg)
