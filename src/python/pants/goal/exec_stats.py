# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import base64
import logging
import textwrap
from collections import Counter
from io import BytesIO
from typing import cast

from pants.engine.internals.scheduler import Workunit
from pants.engine.rules import collect_rules, rule
from pants.engine.streaming_workunit_handler import (
    StreamingWorkunitContext,
    WorkunitsCallback,
    WorkunitsCallbackFactory,
    WorkunitsCallbackFactoryRequest,
)
from pants.engine.unions import UnionRule
from pants.option.subsystem import Subsystem

logger = logging.getLogger(__name__)


class ExecStatsSubsystem(Subsystem):
    options_scope = "exec-stats"
    help = "An aggregator for Pants execution stats, such as cache metrics."

    @classmethod
    def register_options(cls, register):
        register(
            "--log",
            advanced=True,
            type=bool,
            default=False,
            help=(
                "At the end of the Pants run, log all counter metrics and histograms, which give "
                "metrics on Pants execution like the number of cache hits.\n\nFor histograms to "
                "work, you must add `hdrhistogram` to `[GLOBAL].plugins`."
            ),
        )

    @property
    def log(self) -> bool:
        return cast(bool, self.options.log)


class ExecStatsCallback(WorkunitsCallback):
    def __init__(self, *, enabled: bool, has_histogram_module: bool) -> None:
        super().__init__()
        self.enabled = enabled
        self.has_histogram_module = has_histogram_module
        self.counters: Counter = Counter()

    def __call__(
        self,
        *,
        started_workunits: tuple[Workunit, ...],
        completed_workunits: tuple[Workunit, ...],
        finished: bool,
        context: StreamingWorkunitContext,
    ) -> None:
        if not self.enabled:
            return

        # Aggregate counters on completed workunits.
        for workunit in completed_workunits:
            if "counters" in workunit:
                for name, value in workunit["counters"].items():
                    self.counters[name] += value

        if not finished:
            return

        # Add any counters with a count of 0.
        for counter in context.run_tracker.counter_names:
            if counter not in self.counters:
                self.counters[counter] = 0

        # Log aggregated counters.
        counter_lines = "\n".join(
            f"  {name}: {count}" for name, count in sorted(self.counters.items())
        )
        logger.info(f"Counters:\n{counter_lines}")

        # Retrieve all of the observation histograms.
        if not self.has_histogram_module:
            return
        from hdrh.histogram import HdrHistogram

        histogram_info = context.get_observation_histograms()
        logger.info("Observation Histograms:")
        for name, encoded_histogram in histogram_info["histograms"].items():
            # Note: The Python library for HDR Histogram will only decode compressed histograms
            # that are further encoded with base64. See
            # https://github.com/HdrHistogram/HdrHistogram_py/issues/29.
            histogram = HdrHistogram.decode(base64.b64encode(encoded_histogram))
            buffer = BytesIO()
            histogram.output_percentile_distribution(buffer, 1)
            logger.info(
                f"  Histogram for `{name}`:\n{textwrap.indent(buffer.getvalue().decode(), '    ')}"
            )


class ExecStatsCallbackFactoryRequest:
    """A unique request type that is installed to trigger construction of the WorkunitsCallback."""


@rule
def construct_callback(
    _: ExecStatsCallbackFactoryRequest, exec_stats: ExecStatsSubsystem
) -> WorkunitsCallbackFactory:
    enabled = exec_stats.log

    has_histogram_module = False
    if enabled:
        try:
            import hdrh.histogram  # noqa: F401
        except ImportError:
            logger.warning(
                "Please run with `--plugins=hdrhistogram` if you would like histograms to be shown "
                "at the end of the run, or permanently add `[GLOBAL].plugins = ['hdrhistogram']`. "
                "This will cause Pants to install the `hdrhistogram` dependency from PyPI."
            )
        else:
            has_histogram_module = True

    return WorkunitsCallbackFactory(
        lambda: ExecStatsCallback(enabled=enabled, has_histogram_module=has_histogram_module)
    )


def rules():
    return [
        UnionRule(WorkunitsCallbackFactoryRequest, ExecStatsCallbackFactoryRequest),
        *collect_rules(),
    ]
