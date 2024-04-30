# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import base64
import datetime
import json
import logging
from collections import Counter
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional, TypedDict

from pants.engine.internals.scheduler import Workunit
from pants.engine.rules import collect_rules, rule
from pants.engine.streaming_workunit_handler import (
    StreamingWorkunitContext,
    WorkunitsCallback,
    WorkunitsCallbackFactory,
    WorkunitsCallbackFactoryRequest,
)
from pants.engine.unions import UnionRule
from pants.option.option_types import BoolOption, EnumOption, StrOption
from pants.option.subsystem import Subsystem
from pants.util.collections import deep_getsizeof
from pants.util.dirutil import safe_open
from pants.util.strutil import softwrap

logger = logging.getLogger(__name__)

HISTOGRAM_PERCENTILES = [25, 50, 75, 90, 95, 99]


class CounterObject(TypedDict):
    name: str
    count: int


class MemorySummaryObject(TypedDict):
    name: str
    count: int
    bytes: int


class ObservationHistogramObject(TypedDict):
    name: str
    min: int
    max: int
    mean: float
    std_dev: float
    total_observations: int
    sum: int


class StatsObject(TypedDict, total=False):
    timestamp: str
    command: str
    counters: list[CounterObject]
    memory_summary: list[MemorySummaryObject]
    observation_histograms: list[ObservationHistogramObject]


class StatsOutputFormat(Enum):
    """Output format for reporting Pants stats.

    text: Report stats in plain text.
    jsonlines: Report stats in JSON Lines text format.
    """

    text = "text"
    jsonlines = "jsonlines"


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
    format = EnumOption(
        default=StatsOutputFormat.text,
        help="Output format for reporting stats.",
    )


def _log_or_write_to_file_plain(output_file: Optional[str], lines: list[str]) -> None:
    """Send text to the stdout or write to the output file (plain text)."""
    if lines:
        text = "\n".join(lines)
        if output_file:
            with safe_open(output_file, "a") as fh:
                fh.write(text)
            logger.info(f"Wrote Pants stats to {output_file}")
        else:
            logger.info(text)


def _log_or_write_to_file_json(output_file: Optional[str], stats_object: StatsObject) -> None:
    """Send JSON Lines single line object to the stdout or write to the file."""
    if not stats_object:
        return

    if not output_file:
        logger.info(json.dumps(stats_object))
        return

    jsonline = json.dumps(stats_object) + "\n"
    with safe_open(output_file, "a") as fh:
        fh.write(jsonline)
    logger.info(f"Wrote Pants stats to {output_file}")


class StatsAggregatorCallback(WorkunitsCallback):
    def __init__(
        self,
        *,
        log: bool,
        memory: bool,
        output_file: Optional[str],
        has_histogram_module: bool,
        format: StatsOutputFormat,
    ) -> None:
        super().__init__()
        self.log = log
        self.memory = memory
        self.output_file = output_file
        self.has_histogram_module = has_histogram_module
        self.format = format

    @property
    def can_finish_async(self) -> bool:
        # We need to finish synchronously for access to the console.
        return False

    def _output_stats_in_plain_text(self, context: StreamingWorkunitContext):
        output_lines = []
        if self.output_file:
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            # have an empty line between stats of different Pants invocations
            space = "\n\n" if Path(self.output_file).exists() else ""
            output_lines.append(
                f"{space}{timestamp} Command: {context.run_tracker.run_information().get('cmd_line')}"
            )

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
            output_lines.append(f"Counters:\n{counter_lines}")

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
            output_lines.append(
                f"Memory summary (total size in bytes, count, name):\n{memory_lines}"
            )

        if not (self.log and self.has_histogram_module):
            _log_or_write_to_file_plain(self.output_file, output_lines)
            return

        from hdrh.histogram import HdrHistogram  # pants: no-infer-dep

        histograms = context.get_observation_histograms()["histograms"]
        if not histograms:
            output_lines.append("No observation histogram were recorded.")
            _log_or_write_to_file_plain(self.output_file, output_lines)
            return

        output_lines.append("Observation histogram summaries:")
        for name, encoded_histogram in histograms.items():
            # Note: The Python library for HDR Histogram will only decode compressed histograms
            # that are further encoded with base64. See
            # https://github.com/HdrHistogram/HdrHistogram_py/issues/29.
            histogram = HdrHistogram.decode(base64.b64encode(encoded_histogram))
            percentile_to_vals = "\n".join(
                f"  p{percentile}: {value}"
                for percentile, value in histogram.get_percentile_to_value_dict(
                    HISTOGRAM_PERCENTILES
                ).items()
            )
            output_lines.append(
                f"Summary of `{name}` observation histogram:\n"
                f"  min: {histogram.get_min_value()}\n"
                f"  max: {histogram.get_max_value()}\n"
                f"  mean: {histogram.get_mean_value():.3f}\n"
                f"  std dev: {histogram.get_stddev():.3f}\n"
                f"  total observations: {histogram.total_count}\n"
                f"  sum: {int(histogram.get_mean_value() * histogram.total_count)}\n"
                f"{percentile_to_vals}"
            )
        _log_or_write_to_file_plain(self.output_file, output_lines)

    def _output_stats_in_json(self, context: StreamingWorkunitContext):
        stats_object: StatsObject = {}

        if self.output_file:
            stats_object["timestamp"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            stats_object["command"] = context.run_tracker.run_information().get("cmd_line", "")

        if self.log:
            # Capture global counters.
            counters = Counter(context.get_metrics())

            # Add any counters with a count of 0.
            for counter in context.run_tracker.counter_names:
                if counter not in counters:
                    counters[counter] = 0

            # Log aggregated counters.
            stats_object["counters"] = [
                {"name": name, "count": count} for name, count in sorted(counters.items())
            ]

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
            memory_lines: list[MemorySummaryObject] = [
                {"bytes": size, "count": count, "name": name}
                for size, count, name in sorted(entries)
            ]
            stats_object["memory_summary"] = memory_lines

        if not (self.log and self.has_histogram_module):
            _log_or_write_to_file_json(self.output_file, stats_object)
            return

        from hdrh.histogram import HdrHistogram  # pants: no-infer-dep

        histograms = context.get_observation_histograms()["histograms"]
        if not histograms:
            stats_object["observation_histograms"] = []
            _log_or_write_to_file_json(self.output_file, stats_object)
            return

        observation_histograms: list[ObservationHistogramObject] = []
        for name, encoded_histogram in histograms.items():
            # Note: The Python library for HDR Histogram will only decode compressed histograms
            # that are further encoded with base64. See
            # https://github.com/HdrHistogram/HdrHistogram_py/issues/29.
            histogram = HdrHistogram.decode(base64.b64encode(encoded_histogram))
            percentile_to_vals = {
                f"p{percentile}": value
                for percentile, value in histogram.get_percentile_to_value_dict(
                    HISTOGRAM_PERCENTILES
                ).items()
            }

            observation_histogram: ObservationHistogramObject = {
                "name": name,
                "min": histogram.get_min_value(),
                "max": histogram.get_max_value(),
                "mean": round(histogram.get_mean_value(), 3),
                "std_dev": round(histogram.get_stddev(), 3),
                "total_observations": histogram.total_count,
                "sum": int(histogram.get_mean_value() * histogram.total_count),
                **percentile_to_vals,  # type: ignore
            }
            observation_histograms.append(observation_histogram)
        stats_object["observation_histograms"] = observation_histograms

        _log_or_write_to_file_json(self.output_file, stats_object)

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

        if StatsOutputFormat.text == self.format:
            self._output_stats_in_plain_text(context)
        elif StatsOutputFormat.jsonlines == self.format:
            self._output_stats_in_json(context)


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
                format=subsystem.format,
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
