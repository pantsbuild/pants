# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field

from pants.engine.streaming_workunit_handler import WorkunitsCallback


def assert_equal_with_printing(
    expected, actual, uniform_formatter: Callable[[str], str] | None = None
):
    """Asserts equality, but also prints the values so they can be compared on failure."""
    str_actual = str(actual)
    print("Expected:")
    print(expected)
    print("Actual:")
    print(str_actual)

    if uniform_formatter is not None:
        expected = uniform_formatter(expected)
        str_actual = uniform_formatter(str_actual)
    assert expected == str_actual


def remove_locations_from_traceback(trace: str) -> str:
    location_pattern = re.compile(r'"/.*", line \d+')
    address_pattern = re.compile(r"0x[0-9a-f]+")
    new_trace = location_pattern.sub("LOCATION-INFO", trace)
    new_trace = address_pattern.sub("0xEEEEEEEEE", new_trace)
    return new_trace


@dataclass
class WorkunitTracker(WorkunitsCallback):
    """This class records every non-empty batch of started and completed workunits received from the
    engine."""

    finished_workunit_chunks: list[list[dict]] = field(default_factory=list)
    started_workunit_chunks: list[list[dict]] = field(default_factory=list)
    finished: bool = False

    @property
    def can_finish_async(self) -> bool:
        return False

    def __call__(self, **kwargs) -> None:
        if kwargs["finished"] is True:
            self.finished = True

        started_workunits = kwargs.get("started_workunits")
        if started_workunits:
            self.started_workunit_chunks.append(started_workunits)

        completed_workunits = kwargs.get("completed_workunits")
        if completed_workunits:
            self.finished_workunit_chunks.append(completed_workunits)
