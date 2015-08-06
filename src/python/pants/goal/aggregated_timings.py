# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from collections import defaultdict

from pants.util.dirutil import safe_mkdir_for


class AggregatedTimings(object):
  """Aggregates timings over multiple invocations of 'similar' work.

  If filepath is not none, stores the timings in that file. Useful for finding bottlenecks."""

  def __init__(self, path=None):
    # Map path -> timing in seconds (a float)
    self._timings_by_path = defaultdict(float)
    self._tool_labels = set()
    self._path = path
    safe_mkdir_for(self._path)

  def add_timing(self, label, secs, is_tool=False):
    """Aggregate timings by label.

    secs - a double, so fractional seconds are allowed.
    is_tool - whether this label represents a tool invocation.
    """
    self._timings_by_path[label] += secs
    if is_tool:
      self._tool_labels.add(label)
    # Check existence in case we're a clean-all. We don't want to write anything in that case.
    if self._path and os.path.exists(os.path.dirname(self._path)):
      with open(self._path, 'w') as f:
        for x in self.get_all():
          f.write('{label}: {timing}\n'.format(**x))

  def get_all(self):
    """Returns all the timings, sorted in decreasing order.

    Each value is a dict: { path: <path>, timing: <timing in seconds> }
    """
    return [{'label': x[0], 'timing': x[1], 'is_tool': x[0] in self._tool_labels}
            for x in sorted(self._timings_by_path.items(), key=lambda x: x[1], reverse=True)]
