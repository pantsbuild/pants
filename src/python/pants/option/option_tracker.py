# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from collections import defaultdict, namedtuple

from pants.option.ranked_value import RankedValue


class OptionTracker(object):
  """Records a history of what options are set and where they came from."""

  OptionHistoryRecord = namedtuple('OptionHistoryRecord', ['value', 'rank', 'details'])

  class OptionHistory(object):
    """Tracks the history of an individual option."""

    def __init__(self):
      self.values = []

    def record_value(self, value, rank, details=None):
      """Record that the option was set to the given value at the given rank.

      :param value: the value the option was set to.
      :param int rank: the rank of the option when it was set to this value.
      :param string details: optional elaboration of where the option came from (eg, a particular
        config file).
      """
      if self.values:
        if self.latest.rank > rank:
          return
        if self.latest.value == value:
          return # No change.
      self.values.append(OptionTracker.OptionHistoryRecord(value, rank, details))

    @property
    def was_overridden(self):
      """A value was overridden if it has rank greater than 'HARDCODED'."""
      if len(self.values) < 2:
        return False
      return self.latest.rank > RankedValue.HARDCODED and self.values[-2].rank > RankedValue.NONE

    @property
    def latest(self):
      """The most recent value this option was set to, or None if it was never set."""
      return self.values[-1] if self.values else None

    def __iter__(self):
      for record in self.values:
        yield record

    def __len__(self):
      return len(self.values)

  def __init__(self):
    self.option_history_by_scope = defaultdict(dict)

  def record_option(self, scope, option, value, rank, details=None):
    """Records that the given option was set to the given value.

    :param string scope: scope of the option.
    :param string option: name of the option.
    :param string value: value the option was set to.
    :param int rank: the rank of the option (Eg, RankedValue.HARDCODED), to keep track of where the
      option came from.
    :param string details: optional additional details about how the option was set (eg, the name of a
      particular config file, if the rank is RankedValue.CONFIG).
    """
    scoped_options = self.option_history_by_scope[scope]
    if option not in scoped_options:
      scoped_options[option] = self.OptionHistory()
    scoped_options[option].record_value(value, rank, details)
