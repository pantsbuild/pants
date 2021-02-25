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
from pants.option.errors import OptionsError
from pants.option.subsystem import Subsystem

logger = logging.getLogger(__name__)


class StatsAggregatorSubsystem(Subsystem):
    options_scope = "stats"
    help = "An aggregator for Pants stats, such as cache metrics."

    @classmethod
    def register_options(cls, register):
        register(
            "--counters",
            type=bool,
            default=False,
            help=(
                "At the end of the Pants run, log counts of how often certain events like cache "
                "reads and cache errors occurred."
            ),
        )
        register(
            "--histograms",
            type=bool,
            default=False,
            help=(
                "At the end of the Pants run, log histograms of observation metrics, e.g. the "
                "time saved thanks to caching.\n\nYou must add `hdrhistogram` to the global "
                "`--plugins` option for this to work."
            ),
        )

    @property
    def counters(self) -> bool:
        return cast(bool, self.options.counters)

    @property
    def histograms(self) -> bool:
        return cast(bool, self.options.histograms)


class StatsAggregatorCallback(WorkunitsCallback):
    def __init__(self, *, counter_enabled: bool, histograms_enabled: bool) -> None:
        super().__init__()
        self.counters_enabled = counter_enabled
        self.histograms_enabled = histograms_enabled
        self.counters: Counter = Counter()

    def __call__(
        self,
        *,
        started_workunits: tuple[Workunit, ...],
        completed_workunits: tuple[Workunit, ...],
        finished: bool,
        context: StreamingWorkunitContext,
    ) -> None:
        if self.counters_enabled:
            for workunit in completed_workunits:
                if "counters" not in workunit:
                    continue
                for name, value in workunit["counters"].items():
                    self.counters[name] += value

        if not finished:
            return

        if self.counters_enabled:
            # Add any counters with a count of 0.
            for counter in context.run_tracker.counter_names:
                if counter not in self.counters:
                    self.counters[counter] = 0

            # Log aggregated counters.
            counter_lines = "\n".join(
                f"  {name}: {count}" for name, count in sorted(self.counters.items())
            )
            logger.info(f"Counters:\n{counter_lines}")

        if self.histograms_enabled:
            from hdrh.histogram import HdrHistogram

            histogram_info = context.get_observation_histograms()
            logger.info("Observation histograms:")
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


class StatsAggregatorCallbackFactoryRequest:
    """A unique request type that is installed to trigger construction of the WorkunitsCallback."""


@rule
def construct_callback(
    _: StatsAggregatorCallbackFactoryRequest, subsystem: StatsAggregatorSubsystem
) -> WorkunitsCallbackFactory:
    if subsystem.histograms:
        try:
            import hdrh.histogram  # noqa: F401
        except ImportError:
            raise OptionsError(
                "`--stats-histograms` is used, but `hdrhistogram` is not in the "
                "global `--plugins` option.\n\nPlease run again with `--plugins=hdrhistogram`  "
                "or add `[GLOBAL].plugins = ['hdrhistogram']` to your `pants.toml`. This will "
                "cause Pants to install the `hdrhistogram` dependency from PyPI."
            )

    return WorkunitsCallbackFactory(
        lambda: StatsAggregatorCallback(
            counter_enabled=subsystem.counters, histograms_enabled=subsystem.histograms
        )
    )


def rules():
    return [
        UnionRule(WorkunitsCallbackFactoryRequest, StatsAggregatorCallbackFactoryRequest),
        *collect_rules(),
    ]
