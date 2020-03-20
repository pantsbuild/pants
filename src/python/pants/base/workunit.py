# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import re
import time
import uuid
from dataclasses import dataclass

from pants.util.dirutil import safe_mkdir_for
from pants.util.logging import LogLevel
from pants.util.memo import memoized_method
from pants.util.rwbuf import FileBackedRWBuf


class WorkUnitLabel:
    """
    :API: public
    """

    # Labels describing a workunit.  Reporting code can use this to decide how to display
    # information about this workunit.
    #
    # Note that a workunit can have multiple labels where this makes sense, e.g., TOOL, COMPILER
    # and NAILGUN.
    SETUP = "SETUP"  # Parsing build files etc.
    GOAL = "GOAL"  # Executing a goal.
    TASK = "TASK"  # Executing a task within a goal.
    GROUP = "GROUP"  # Executing a group.

    BOOTSTRAP = "BOOTSTRAP"  # Invocation of code to fetch a tool.
    TOOL = "TOOL"  # Single invocations of a tool.
    MULTITOOL = "MULTITOOL"  # Multiple consecutive invocations of the same tool.
    COMPILER = "COMPILER"  # Invocation of a compiler.
    LINKER = "LINKER"  # Invocation of a linker.

    TEST = "TEST"  # Running a test.
    JVM = "JVM"  # Running a tool via the JVM.
    NAILGUN = "NAILGUN"  # Running a tool via nailgun.
    RUN = "RUN"  # Running a binary.
    REPL = "REPL"  # Running a repl.
    PREP = "PREP"  # Running a prep command
    LINT = "LINT"  # Running a lint or static analysis tool.

    # Do not attempt to print workunit's label upon invocation
    # This has nothing to do with a process's own stderr/stdout.
    SUPPRESS_LABEL = "SUPPRESS_LABEL"

    @classmethod
    @memoized_method
    def keys(cls):
        """
        :API: public
        """
        return [key for key in dir(cls) if not key.startswith("_") and key.isupper()]


class WorkUnit:
    """A hierarchical unit of work, for the purpose of timing and reporting.

    A WorkUnit can be subdivided into further WorkUnits. The WorkUnit concept is deliberately
    decoupled from the goal/task hierarchy. This allows some flexibility in having, say,
    sub-units inside a task. E.g., there might be one WorkUnit representing an entire pants run,
    and that can be subdivided into WorkUnits for each goal. Each of those can be subdivided into
    WorkUnits for each task, and a task can subdivide that into further work units, if finer-grained
    timing and reporting is needed.

    :API: public
    """

    # The outcome of a workunit.
    # It can only be set to a new value <= the old one.
    ABORTED = 0
    FAILURE = 1
    WARNING = 2
    SUCCESS = 3
    UNKNOWN = 4

    # Generic workunit log config.
    #   log_level: Display log messages up to this level.
    #   color: log color settings.
    @dataclass(frozen=True)
    class LogConfig:
        log_level: LogLevel
        colors: bool

    @staticmethod
    def outcome_string(outcome):
        """Returns a human-readable string describing the outcome.

        :API: public
        """
        return ["ABORTED", "FAILURE", "WARNING", "SUCCESS", "UNKNOWN"][outcome]

    def __init__(self, run_info_dir, parent, name, labels=None, cmd="", log_config=None):
        """
        - run_info_dir: The path of the run_info_dir from the RunTracker that tracks this WorkUnit.
        - parent: The containing workunit, if any. E.g., 'compile' might contain 'java', 'scala' etc.,
                  'scala' might contain 'compile', 'split' etc.
        - name: A short name for this work. E.g., 'resolve', 'compile', 'scala', 'zinc'.
        - labels: An optional iterable of labels. The reporters can use this to decide how to
                  display information about this work.
        - cmd: An optional longer string representing this work.
                E.g., the cmd line of a compiler invocation.
        - log_config: An optional tuple of registered options affecting reporting output.
        """
        self._outcome = WorkUnit.UNKNOWN

        self.run_info_dir = run_info_dir
        self.parent = parent
        self.children = []

        # When a workunit is created the zipkin_span parameter is set to None.
        # The zipkin_span parameter gets value when run_tracker.report.start_workunit(workunit)
        # is called. The zipkin_span parameter cannot be set when the workunit is created because of
        # specifics of the py_zipkin API and how info about workunits is recorded.
        self.zipkin_span = None

        self.name = name
        self.labels = set(labels or ())
        self.cmd = cmd
        self.id = uuid.uuid4()
        self.log_config = log_config

        # In seconds since the epoch. Doubles, to account for fractional seconds.
        self.start_time = 0
        self.end_time = 0

        # A workunit may have multiple outputs, which we identify by a name.
        # E.g., a tool invocation may have 'stdout', 'stderr', 'debug_log' etc.
        self._outputs = {}  # name -> output buffer.
        self._output_paths = {}

        # Do this last, as the parent's _self_time() might get called before we're
        # done initializing ourselves.
        # TODO: Ensure that a parent can't be ended before all its children are.

        if self.parent:
            if not log_config:
                self.log_config = self.parent.log_config
            self.parent.children.append(self)

    def has_label(self, label):
        """
        :API: public
        """
        return label in self.labels

    def start(self, start_time=None):
        """Mark the time at which this workunit started."""
        self.start_time = start_time or time.time()

    def end(self):
        """Mark the time at which this workunit ended."""
        self.end_time = time.time()

        return self.path(), self.duration(), self._self_time(), self.has_label(WorkUnitLabel.TOOL)

    def cleanup(self):
        """Cleanup by closing all output streams."""
        for output in self._outputs.values():
            output.close()

    def outcome(self):
        """Returns the outcome of this workunit.

        :API: public
        """
        return self._outcome

    def set_outcome(self, outcome):
        """Set the outcome of this work unit.

        We can set the outcome on a work unit directly, but that outcome will also be affected by
        those of its subunits. The right thing happens: The outcome of a work unit is the worst
        outcome of any of its subunits and any outcome set on it directly.
        """
        if outcome not in range(0, 5):
            raise Exception("Invalid outcome: {}".format(outcome))

        if outcome < self._outcome:
            self._outcome = outcome
            if self.parent:
                self.parent.set_outcome(self._outcome)

    _valid_name_re = re.compile(r"\w+")

    def output(self, name):
        """Returns the output buffer for the specified output name (e.g., 'stdout'), creating it if
        necessary.

        :API: public
        """
        m = WorkUnit._valid_name_re.match(name)
        if not m or m.group(0) != name:
            raise Exception("Invalid output name: {}".format(name))
        if name not in self._outputs:
            workunit_name = re.sub(r"\W", "_", self.name)
            path = os.path.join(
                self.run_info_dir,
                "tool_outputs",
                "{workunit_name}-{id}.{output_name}".format(
                    workunit_name=workunit_name, id=self.id, output_name=name
                ),
            )
            safe_mkdir_for(path)
            self._outputs[name] = FileBackedRWBuf(path)
            self._output_paths[name] = path
        return self._outputs[name]

    def outputs(self):
        """Returns the map of output name -> output buffer.

        :API: public
        """
        return self._outputs

    def output_paths(self):
        """Returns the map of output name -> path of the output file.

        :API: public
        """
        return self._output_paths

    def duration(self):
        """Returns the time (in fractional seconds) spent in this workunit and its children.

        :API: public
        """
        return (self.end_time or time.time()) - self.start_time

    @property
    def start_time_string(self):
        """A convenient string representation of start_time.

        :API: public
        """
        return time.strftime("%H:%M:%S", time.localtime(self.start_time))

    @property
    def start_delta_string(self):
        """A convenient string representation of how long after the run started we started.

        :API: public
        """
        delta = int(self.start_time) - int(self.root().start_time)
        return "{:02}:{:02}".format(int(delta / 60), delta % 60)

    def root(self):
        """
        :API: public
        """
        ret = self
        while ret.parent is not None:
            ret = ret.parent
        return ret

    def is_background(self, background_root_workunit):
        """Returns True if this workunit is a background root workunit or its successor.

        :param WorkUnit background_root_workunit: parent of all background workunits.

        :API: public
        """
        curr_workunit = self
        while curr_workunit is not None:
            if curr_workunit is background_root_workunit:
                return True
            curr_workunit = curr_workunit.parent
        return False

    def ancestors(self):
        """Returns a list consisting of this workunit and those enclosing it, up to the root.

        :API: public
        """
        ret = []
        workunit = self
        while workunit is not None:
            ret.append(workunit)
            workunit = workunit.parent
        return ret

    def path(self):
        """Returns a path string for this workunit, E.g., 'all:compile:jvm:scalac'.

        :API: public
        """
        return ":".join(reversed([w.name for w in self.ancestors()]))

    def unaccounted_time(self):
        """Returns non-leaf time spent in this workunit.

        This assumes that all major work should be done in leaves.
        TODO: Is this assumption valid?

        :API: public
        """
        return 0 if len(self.children) == 0 else self._self_time()

    def to_dict(self):
        """Useful for providing arguments to templates.

        :API: public
        """
        ret = {}
        for key in [
            "name",
            "cmd",
            "id",
            "start_time",
            "end_time",
            "outcome",
            "start_time_string",
            "start_delta_string",
        ]:
            val = getattr(self, key)
            ret[key] = val() if hasattr(val, "__call__") else val
        ret["parent"] = self.parent.to_dict() if self.parent else None
        return ret

    def _self_time(self):
        """Returns the time spent in this workunit outside of any children."""
        return self.duration() - sum([child.duration() for child in self.children])
