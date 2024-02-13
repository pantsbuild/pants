# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import base64
import logging
from collections import Counter
from dataclasses import dataclass
from typing import Optional

from pants.engine.internals.scheduler import Workunit
from pants.engine.rules import collect_rules, rule
from pants.engine.streaming_workunit_handler import (
    StreamingWorkunitContext,
    WorkunitsCallback,
    WorkunitsCallbackFactory,
    WorkunitsCallbackFactoryRequest,
)
from pants.engine.unions import UnionRule
from pants.option.option_types import BoolOption, StrOption
from pants.option.subsystem import Subsystem
from pants.util.collections import deep_getsizeof
from pants.util.strutil import softwrap

logger = logging.getLogger(__name__)


class StatsAggregatorSubsystem(Subsystem):
    options_scope = "stats"
    help = "An aggregator for Pants stats, such as cache metrics."

    log = BoolOption(
        default=False,
        help=softwrap(
            """
            At the end of the Pants run, log all counter metrics and summaries of
            observation histograms, e.g. the number of cache hits and the time saved by
            caching.

            For histogram summaries to work, you must add `hdrhistogram` to `[GLOBAL].plugins`.
            """
        ),
        advanced=True,
    )
    memory_summary = BoolOption(
        default=False,
        help=softwrap(
            """
            At the end of the Pants run, report a summary of memory usage.

            Keys are the total size in bytes, the count, and the name. Note that the total size
            is for all instances added together, so you can use total_size // count to get the
            average size.
            """
        ),
        advanced=True,
    )
    output_file = StrOption(
        default=None,
        metavar="<path>",
        help="Output the stats to this file. If unspecified, outputs to stdout.",
    )


def _log_or_write_to_file(output_file: Optional[str], text: str) -> None:
    """Send text to the stdout or write to the output file."""
    if text:
        if output_file:
            with safe_open(output_file, "w") as fh:
                fh.write(text)
            logger.info(f"Wrote Pants stats to {output_file}")
        else:
            logger.info(text)


class StatsAggregatorCallback(WorkunitsCallback):
    def __init__(
        self, *, log: bool, memory: bool, output_file: Optional[str], has_histogram_module: bool
    ) -> None:
        super().__init__()
        self.log = log
        self.memory = memory
        self.output_file = output_file
        self.has_histogram_module = has_histogram_module

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
        if not finished:
            return

        output_contents = ""

        if self.log:
            # Capture global counters.
            counters = Counter(context.get_metrics())

            # Add any counters with a count of 0.
            for counter in context.run_tracker.counter_names:
                if counter not in counters:
                    counters[counter] = 0

            # Log aggregated counters.
            counter_lines = "\n".join(
                f"  {name}: {count}" for name, count in sorted(counters.items())
            )
            output_contents += f"Counters:\n{counter_lines}"

        if self.memory:
            ids: set[int] = set()
            count_by_type: Counter[type] = Counter()
            sizes_by_type: Counter[type] = Counter()

            items, rust_sizes = context._scheduler.live_items()
            for item in items:
                count_by_type[type(item)] += 1
                sizes_by_type[type(item)] += deep_getsizeof(item, ids)

            entries = [
                (size, count_by_type[typ], f"{typ.__module__}.{typ.__qualname__}")
                for typ, size in sizes_by_type.items()
            ]
            entries.extend(
                (size, count, f"(native) {name}") for name, (count, size) in rust_sizes.items()
            )
            memory_lines = "\n".join(
                f"  {size}\t\t{count}\t\t{name}" for size, count, name in sorted(entries)
            )
            output_contents += (
                f"\nMemory summary (total size in bytes, count, name):\n{memory_lines}"
            )

        if not (self.log and self.has_histogram_module):
            _log_or_write_to_file(self.output_file, output_contents)
            return

        from hdrh.histogram import HdrHistogram  # pants: no-infer-dep

        histograms = context.get_observation_histograms()["histograms"]
        if not histograms:
            output_contents += "\nNo observation histogram were recorded."
            _log_or_write_to_file(self.output_file, output_contents)
            return

        output_contents += "\nObservation histogram summaries:"
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
            output_contents += (
                f"\nSummary of `{name}` observation histogram:\n"
                f"  min: {histogram.get_min_value()}\n"
                f"  max: {histogram.get_max_value()}\n"
                f"  mean: {histogram.get_mean_value():.3f}\n"
                f"  std dev: {histogram.get_stddev():.3f}\n"
                f"  total observations: {histogram.total_count}\n"
                f"  sum: {int(histogram.get_mean_value() * histogram.total_count)}\n"
                f"{percentile_to_vals}"
            )
        _log_or_write_to_file(self.output_file, output_contents)


@dataclass(frozen=True)
class StatsAggregatorCallbackFactoryRequest:
    """A unique request type that is installed to trigger construction of the WorkunitsCallback."""


@rule
def construct_callback(
    _: StatsAggregatorCallbackFactoryRequest, subsystem: StatsAggregatorSubsystem
) -> WorkunitsCallbackFactory:
    has_histogram_module = False
    if subsystem.log:
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
        lambda: (
            StatsAggregatorCallback(
                log=subsystem.log,
                memory=subsystem.memory_summary,
                output_file=subsystem.output_file,
                has_histogram_module=has_histogram_module,
            )
            if subsystem.log or subsystem.memory_summary
            else None
        )
    )


def rules():
    return [
        UnionRule(WorkunitsCallbackFactoryRequest, StatsAggregatorCallbackFactoryRequest),
        *collect_rules(),
    ]
