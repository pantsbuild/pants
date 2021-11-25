# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import base64
import logging
from collections import Counter
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


class StatsAggregatorSubsystem(Subsystem):
    options_scope = "stats"
    help = "An aggregator for Pants stats, such as cache metrics."

    @classmethod
    def register_options(cls, register):
        register(
            "--log",
            advanced=True,
            type=bool,
            default=False,
            help=(
                "At the end of the Pants run, log all counter metrics and summaries of "
                "observation histograms, e.g. the number of cache hits and the time saved by "
                "caching.\n\nFor histogram summaries to work, you must add `hdrhistogram` to "
                "`[GLOBAL].plugins`."
            ),
        )

    @property
    def log(self) -> bool:
        return cast(bool, self.options.log)


class StatsAggregatorCallback(WorkunitsCallback):
    def __init__(self, *, has_histogram_module: bool) -> None:
        super().__init__()
        self.has_histogram_module = has_histogram_module
        self.counters: Counter = Counter()

    @property
    def can_finish_async(self) -> bool:
        # We need to finish synchronously for access to the console.
        return False

    def __call__(
        self,
        *,
        started_workunits: tuple[Workunit, ...],
        completed_workunits: tuple[Workunit, ...],
        finished: bool,
        context: StreamingWorkunitContext,
    ) -> None:
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

        if not self.has_histogram_module:
            return
        from hdrh.histogram import HdrHistogram

        histograms = context.get_observation_histograms()["histograms"]
        if not histograms:
            logger.info("No observation histogram were recorded.")
            return

        logger.info("Observation histogram summaries:")
        for name, encoded_histogram in histograms.items():
            # Note: The Python library for HDR Histogram will only decode compressed histograms
            # that are further encoded with base64. See
            # https://github.com/HdrHistogram/HdrHistogram_py/issues/29.
            histogram = HdrHistogram.decode(base64.b64encode(encoded_histogram))
            percentile_to_vals = "\n".join(
                f"  p{percentile}: {value}"
                for percentile, value in histogram.get_percentile_to_value_dict(
                    [25, 50, 75, 90, 95, 99]
                ).items()
            )
            logger.info(
                f"Summary of `{name}` observation histogram:\n"
                f"  min: {histogram.get_min_value()}\n"
                f"  max: {histogram.get_max_value()}\n"
                f"  mean: {histogram.get_mean_value():.3f}\n"
                f"  std dev: {histogram.get_stddev():.3f}\n"
                f"  total observations: {histogram.total_count}\n"
                f"{percentile_to_vals}"
            )


class StatsAggregatorCallbackFactoryRequest:
    """A unique request type that is installed to trigger construction of the WorkunitsCallback."""


@rule
def construct_callback(
    _: StatsAggregatorCallbackFactoryRequest, subsystem: StatsAggregatorSubsystem
) -> WorkunitsCallbackFactory:
    enabled = subsystem.log
    has_histogram_module = False
    if enabled:
        try:
            import hdrh.histogram  # noqa: F401
        except ImportError:
            logger.warning(
                "Please run with `--plugins=hdrhistogram` if you would like histogram summaries to "
                "be shown at the end of the run, or permanently add "
                "`[GLOBAL].plugins = ['hdrhistogram']`. This will cause Pants to install "
                "the `hdrhistogram` dependency from PyPI."
            )
        else:
            has_histogram_module = True

    return WorkunitsCallbackFactory(
        lambda: StatsAggregatorCallback(has_histogram_module=has_histogram_module)
        if enabled
        else None
    )


def rules():
    return [
        UnionRule(WorkunitsCallbackFactoryRequest, StatsAggregatorCallbackFactoryRequest),
        *collect_rules(),
    ]
