# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os
import re
import time
import uuid


from pants.rwbuf.read_write_buffer import FileBackedRWBuf
from pants.util.dirutil import safe_mkdir_for


class WorkUnit(object):
  """A hierarchical unit of work, for the purpose of timing and reporting.

  A WorkUnit can be subdivided into further WorkUnits. The WorkUnit concept is deliberately
  decoupled from the phase/task hierarchy. This allows some flexibility in having, say,
  sub-units inside a task. E.g., there might be one WorkUnit representing an entire pants run,
  and that can be subdivided into WorkUnits for each phase. Each of those can be subdivided into
  WorkUnits for each task, and a task can subdivide that into further work units, if finer-grained
  timing and reporting is needed.
  """

  # The outcome of a workunit.
  # It can only be set to a new value <= the old one.
  ABORTED = 0
  FAILURE = 1
  WARNING = 2
  SUCCESS = 3
  UNKNOWN = 4

  @staticmethod
  def choose_for_outcome(outcome, aborted_val, failure_val, warning_val, success_val, unknown_val):
    """Returns one of the 5 arguments, depending on the outcome."""
    if outcome not in range(0, 5):
      raise Exception('Invalid outcome: %s' % outcome)
    return (aborted_val, failure_val, warning_val, success_val, unknown_val)[outcome]

  @staticmethod
  def outcome_string(outcome):
    """Returns a human-readable string describing the outcome."""
    return WorkUnit.choose_for_outcome(outcome,
                                       'ABORTED', 'FAILURE', 'WARNING', 'SUCCESS', 'UNKNOWN')

  # Labels describing a workunit.  Reporting code can use this to decide how to display
  # information about this workunit.
  #
  # Note that a workunit can have multiple labels where this makes sense, e.g., TOOL, COMPILER
  # and NAILGUN.
  SETUP = 0      # Parsing build files etc.
  PHASE = 1      # Executing a phase.
  GOAL = 2       # Executing a goal.
  GROUP = 3      # Executing a group.

  BOOTSTRAP = 4  # Invocation of code to fetch a tool.
  TOOL = 5       # Single invocations of a tool.
  MULTITOOL = 6  # Multiple consecutive invocations of the same tool.
  COMPILER = 7   # Invocation of a compiler.

  TEST = 8       # Running a test.
  JVM = 9        # Running a tool via the JVM.
  NAILGUN = 10   # Running a tool via nailgun.
  RUN = 11       # Running a binary.
  REPL = 12      # Running a repl.

  def __init__(self, run_tracker, parent, name, labels=None, cmd=''):
    """
    - run_tracker: The RunTracker that tracks this WorkUnit.
    - parent: The containing workunit, if any. E.g., 'compile' might contain 'java', 'scala' etc.,
              'scala' might contain 'compile', 'split' etc.
    - name: A short name for this work. E.g., 'resolve', 'compile', 'scala', 'zinc'.
    - labels: An optional iterable of labels. The reporters can use this to decide how to
              display information about this work.
    - cmd: An optional longer string representing this work.
           E.g., the cmd line of a compiler invocation.
    """
    self._outcome = WorkUnit.UNKNOWN

    self.run_tracker = run_tracker
    self.parent = parent
    self.children = []

    self.name = name
    self.labels = set(labels or ())
    self.cmd = cmd
    self.id = uuid.uuid4()

    # In seconds since the epoch. Doubles, to account for fractional seconds.
    self.start_time = 0
    self.end_time = 0

    # A workunit may have multiple outputs, which we identify by a name.
    # E.g., a tool invocation may have 'stdout', 'stderr', 'debug_log' etc.
    self._outputs = {}  # name -> output buffer.

    # Do this last, as the parent's _self_time() might get called before we're
    # done initializing ourselves.
    # TODO: Ensure that a parent can't be ended before all its children are.
    if self.parent:
      self.parent.children.append(self)

  def has_label(self, label):
    return label in self.labels

  def start(self):
    """Mark the time at which this workunit started."""
    self.start_time = time.time()

  def end(self):
    """Mark the time at which this workunit ended."""
    self.end_time = time.time()
    for output in self._outputs.values():
      output.close()
    is_tool = self.has_label(WorkUnit.TOOL)
    path = self.path()
    self.run_tracker.cumulative_timings.add_timing(path, self.duration(), is_tool)
    self.run_tracker.self_timings.add_timing(path, self._self_time(), is_tool)

  def outcome(self):
    """Returns the outcome of this workunit."""
    return self._outcome

  def set_outcome(self, outcome):
    """Set the outcome of this work unit.

    We can set the outcome on a work unit directly, but that outcome will also be affected by
    those of its subunits. The right thing happens: The outcome of a work unit is the
    worst outcome of any of its subunits and any outcome set on it directly."""
    if outcome < self._outcome:
      self._outcome = outcome
      self.choose(0, 0, 0, 0, 0)  # Dummy call, to validate outcome.
      if self.parent: self.parent.set_outcome(self._outcome)

  _valid_name_re = re.compile(r'\w+')

  def output(self, name):
    """Returns the output buffer for the specified output name (e.g., 'stdout')."""
    m = WorkUnit._valid_name_re.match(name)
    if not m or m.group(0) != name:
      raise Exception('Invalid output name: %s' % name)
    if name not in self._outputs:
      path = os.path.join(self.run_tracker.info_dir, 'tool_outputs', '%s.%s' % (self.id, name))
      safe_mkdir_for(path)
      self._outputs[name] = FileBackedRWBuf(path)
    return self._outputs[name]

  def outputs(self):
    """Returns the map of output name -> output buffer."""
    return self._outputs

  def choose(self, aborted_val, failure_val, warning_val, success_val, unknown_val):
    """Returns one of the 5 arguments, depending on our outcome."""
    return WorkUnit.choose_for_outcome(self._outcome,
                            aborted_val, failure_val, warning_val, success_val, unknown_val)

  def duration(self):
    """Returns the time (in fractional seconds) spent in this workunit and its children."""
    return (self.end_time or time.time()) - self.start_time

  def start_time_string(self):
    """A convenient string representation of start_time."""
    return time.strftime('%H:%M:%S', time.localtime(self.start_time))

  def start_delta_string(self):
    """A convenient string representation of how long after the run started we started."""
    delta = int(self.start_time) - int(self.root().start_time)
    return '%02d:%02d' % (delta / 60, delta % 60)

  def root(self):
    ret = self
    while ret.parent is not None:
      ret = ret.parent
    return ret

  def ancestors(self):
    """Returns a list consisting of this workunit and those enclosing it, up to the root."""
    ret = []
    workunit = self
    while workunit is not None:
      ret.append(workunit)
      workunit = workunit.parent
    return ret

  def path(self):
    """Returns a path string for this workunit, E.g., 'all:compile:jvm:scalac'."""
    return ':'.join(reversed([w.name for w in self.ancestors()]))

  def unaccounted_time(self):
    """Returns non-leaf time spent in this workunit.

    This assumes that all major work should be done in leaves.
    TODO: Is this assumption valid?
    """
    return 0 if len(self.children) == 0 else self._self_time()

  def to_dict(self):
    """Useful for providing arguments to templates."""
    ret = {}
    for key in ['name', 'cmd', 'id', 'start_time', 'end_time',
                'outcome', 'start_time_string', 'start_delta_string']:
      val = getattr(self, key)
      ret[key] = val() if hasattr(val, '__call__') else val
    ret['parent'] = self.parent.to_dict() if self.parent else None
    return ret

  def _self_time(self):
    """Returns the time spent in this workunit outside of any children."""
    return self.duration() - sum([child.duration() for child in self.children])
