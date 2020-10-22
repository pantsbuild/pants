# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from collections import defaultdict
from typing import Dict, List, Optional, Set, Union

from pants.util.dirutil import safe_mkdir_for

TimingData = List[Dict[str, Union[str, float, bool]]]


class AggregatedTimings:
    """Aggregates timings over multiple invocations of 'similar' work.

    If filepath is not none, stores the timings in that file. Useful for finding bottlenecks.
    """

    def __init__(self, path: Optional[str] = None) -> None:
        # Map path -> timing in seconds (a float)
        self._timings_by_path: Dict[str, float] = defaultdict(float)
        self._tool_labels: Set[str] = set()
        self._path = path
        if path:
            safe_mkdir_for(path)

    def add_timing(self, label: str, secs: float, is_tool: bool = False) -> None:
        """Aggregate timings by label.

        secs - a double, so fractional seconds are allowed.
        is_tool - whether this label represents a tool invocation.
        """
        self._timings_by_path[label] += secs
        if is_tool:
            self._tool_labels.add(label)
        if not self._path or not os.path.exists(os.path.dirname(self._path)):
            # Check existence in case we're a clean-all. We don't want to write anything in that case.
            return
        with open(self._path, "w") as fl:
            for timing_row in self.get_all():
                fl.write("{label}: {timing}\n".format(**timing_row))

    def get_all(self) -> TimingData:
        """Returns all the timings, sorted in decreasing order.

        Each value is a dict: { path: <path>, timing: <timing in seconds> }
        """
        return [
            {"label": row[0], "timing": row[1], "is_tool": row[0] in self._tool_labels}
            for row in sorted(self._timings_by_path.items(), key=lambda x: x[1], reverse=True)
        ]
