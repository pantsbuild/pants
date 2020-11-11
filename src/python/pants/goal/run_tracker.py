# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json
import logging
import os
import sys
import threading
import time
import uuid
from collections import OrderedDict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from pants.base.exiter import PANTS_FAILED_EXIT_CODE, PANTS_SUCCEEDED_EXIT_CODE, ExitCode
from pants.base.run_info import RunInfo
from pants.base.workunit import WorkUnit, WorkUnitLabel
from pants.engine.internals.native import Native
from pants.goal.aggregated_timings import AggregatedTimings
from pants.option.config import Config
from pants.option.options import Options
from pants.option.options_fingerprinter import CoercingOptionEncoder
from pants.option.scope import GLOBAL_SCOPE, GLOBAL_SCOPE_CONFIG_SECTION
from pants.option.subsystem import Subsystem
from pants.reporting.report import Report
from pants.util.dirutil import relative_symlink, safe_file_dump

logger = logging.getLogger(__name__)


class RunTrackerOptionEncoder(CoercingOptionEncoder):
    """Use the json encoder we use for making options hashable to support datatypes.

    This encoder also explicitly allows OrderedDict inputs, as we accept more than just option
    values when encoding stats to json.
    """

    def default(self, o):
        if isinstance(o, OrderedDict):
            return o
        return super().default(o)


class RunTracker(Subsystem):
    """Tracks and times the execution of a pants run."""

    options_scope = "run-tracker"

    # The name of the tracking root for the main thread (and the foreground worker threads).
    DEFAULT_ROOT_NAME = "main"

    # The name of the tracking root for the background worker threads.
    BACKGROUND_ROOT_NAME = "background"

    @classmethod
    def register_options(cls, register):
        register(
            "--stats-local-json-file",
            advanced=True,
            default=None,
            help="Write stats to this local json file on run completion.",
        )
        register(
            "--stats-option-scopes-to-record",
            advanced=True,
            type=list,
            default=[],
            help="Option scopes to record in stats on run completion. "
            "Options may be selected by joining the scope and the option with a ^ character, "
            "i.e. to get option `pantsd` in the GLOBAL scope, you'd pass `GLOBAL^pantsd`. "
            "Add a '*' to the list to capture all known scopes.",
        )

    def __init__(self, *args, **kwargs):
        """
        :API: public
        """
        super().__init__(*args, **kwargs)
        self._run_timestamp = time.time()
        self._cmd_line = " ".join(["pants"] + sys.argv[1:])
        self._v2_goal_rule_names: Tuple[str, ...] = tuple()

        self.run_uuid = uuid.uuid4().hex
        # Select a globally unique ID for the run, that sorts by time.
        millis = int((self._run_timestamp * 1000) % 1000)
        # run_uuid is used as a part of run_id and also as a trace_id for Zipkin tracing
        str_time = time.strftime("%Y_%m_%d_%H_%M_%S", time.localtime(self._run_timestamp))
        self.run_id = f"pants_run_{str_time}_{millis}_{self.run_uuid}"

        # Initialized in `initialize()`.
        self.run_info_dir = None
        self.run_info = None
        self.cumulative_timings = None
        self.self_timings = None

        # Initialized in `start()`.
        self.report = None
        self._main_root_workunit = None
        self._all_options = None

        # A lock to ensure that adding to stats at the end of a workunit
        # operates thread-safely.
        self._stats_lock = threading.Lock()

        # Log of success/failure/aborted for each workunit.
        self.outcomes = {}

        # self._threadlocal.current_workunit contains the current workunit for the calling thread.
        # Note that multiple threads may share a name (e.g., all the threads in a pool).
        self._threadlocal = threading.local()

        # For background work.  Created lazily if needed.
        self._background_root_workunit = None

        self._aborted = False

        self._end_memoized_result: Optional[ExitCode] = None

        self.native = Native()

        self.run_logs_file: Optional[Path] = None

    @property
    def v2_goals_rule_names(self) -> Tuple[str, ...]:
        return self._v2_goal_rule_names

    def register_thread(self, parent_workunit):
        """Register the parent workunit for all work in the calling thread.

        Multiple threads may have the same parent (e.g., all the threads in a pool).
        """
        self._threadlocal.current_workunit = parent_workunit

    def is_under_background_root(self, workunit):
        """Is the workunit running under the background thread's root."""
        return workunit.is_background(self._background_root_workunit)

    def is_background_root_workunit(self, workunit):
        return workunit is self._background_root_workunit

    def start(self, all_options: Options, run_start_time: float) -> None:
        """Start tracking this pants run."""
        if self.run_info:
            raise AssertionError("RunTracker.start must not be called multiple times.")

        # Initialize the run.

        info_dir = os.path.join(self.options.pants_workdir, self.options_scope)
        self.run_info_dir = os.path.join(info_dir, self.run_id)
        self.run_info = RunInfo(os.path.join(self.run_info_dir, "info"))
        self.run_info.add_basic_info(self.run_id, self._run_timestamp)
        self.run_info.add_info("cmd_line", self._cmd_line)

        # Create a 'latest' symlink, after we add_infos, so we're guaranteed that the file exists.
        link_to_latest = os.path.join(os.path.dirname(self.run_info_dir), "latest")

        relative_symlink(self.run_info_dir, link_to_latest)

        # Time spent in a workunit, including its children.
        self.cumulative_timings = AggregatedTimings(
            os.path.join(self.run_info_dir, "cumulative_timings")
        )

        # Time spent in a workunit, not including its children.
        self.self_timings = AggregatedTimings(os.path.join(self.run_info_dir, "self_timings"))
        # pantsd stats.
        self._pantsd_metrics: Dict[str, int] = dict()

        self._all_options = all_options

        self.report = Report()
        self.report.open()

        # And create the workunit.
        self._main_root_workunit = WorkUnit(
            run_info_dir=self.run_info_dir, parent=None, name=RunTracker.DEFAULT_ROOT_NAME, cmd=None
        )
        self.register_thread(self._main_root_workunit)
        # Set the true start time in the case of e.g. the daemon.
        self._main_root_workunit.start(run_start_time)
        self.report.start_workunit(self._main_root_workunit)

        goal_names: Tuple[str, ...] = tuple(all_options.goals)
        self._v2_goal_rule_names = goal_names

        self.run_logs_file = Path(self.run_info_dir, "logs")
        self.native.set_per_run_log_path(str(self.run_logs_file))

    def set_root_outcome(self, outcome):
        """Useful for setup code that doesn't have a reference to a workunit."""
        self._main_root_workunit.set_outcome(outcome)

    def set_pantsd_scheduler_metrics(self, metrics: Dict[str, int]) -> None:
        self._pantsd_metrics = metrics

    @property
    def pantsd_scheduler_metrics(self) -> Dict[str, int]:
        return dict(self._pantsd_metrics)  # defensive copy

    @classmethod
    def _json_dump_options(cls, stats: dict) -> str:
        return json.dumps(stats, cls=RunTrackerOptionEncoder)

    @classmethod
    def write_stats_to_json(cls, file_name: str, stats: dict) -> None:
        """Write stats to a local json file."""
        params = cls._json_dump_options(stats)
        try:
            safe_file_dump(file_name, params, mode="w")
        except Exception as e:  # Broad catch - we don't want to fail in stats related failure.
            print(
                f"WARNING: Failed to write stats to {file_name} due to Error: {e!r}",
                file=sys.stderr,
            )

    def run_information(self):
        """Basic information about this run."""
        run_information = self.run_info.get_as_dict()
        return run_information

    def _stats(self) -> dict:
        stats = {
            "run_info": self.run_information(),
            "pantsd_stats": self.pantsd_scheduler_metrics,
            "cumulative_timings": self.cumulative_timings.get_all(),
            "recorded_options": self.get_options_to_record(),
        }
        return stats

    def store_stats(self):
        """Store stats about this run in local and optionally remote stats dbs."""
        stats = self._stats()

        # Write stats to user-defined json file.
        stats_json_file_name = self.options.stats_local_json_file
        if stats_json_file_name:
            self.write_stats_to_json(stats_json_file_name, stats)

    def has_ended(self) -> bool:
        return self._end_memoized_result is not None

    def end(self) -> ExitCode:
        """This pants run is over, so stop tracking it.

        Note: If end() has been called once, subsequent calls are no-ops.

        :return: PANTS_SUCCEEDED_EXIT_CODE or PANTS_FAILED_EXIT_CODE
        """
        if self._end_memoized_result is not None:
            return self._end_memoized_result

        self.end_workunit(self._main_root_workunit)

        outcome = self._main_root_workunit.outcome()
        if self._background_root_workunit:
            outcome = min(outcome, self._background_root_workunit.outcome())
        outcome_str = WorkUnit.outcome_string(outcome)

        if self.run_info.get_info("outcome") is None:
            # If the goal is clean-all then the run info dir no longer exists, so ignore that error.
            self.run_info.add_info("outcome", outcome_str, ignore_errors=True)

        self.report.close()
        self.store_stats()

        run_failed = outcome in [WorkUnit.FAILURE, WorkUnit.ABORTED]
        result = PANTS_FAILED_EXIT_CODE if run_failed else PANTS_SUCCEEDED_EXIT_CODE
        self._end_memoized_result = result

        self.native.set_per_run_log_path(None)

        return self._end_memoized_result

    def end_workunit(self, workunit):
        path, duration, self_time, is_tool = workunit.end()
        self.report.end_workunit(workunit)
        workunit.cleanup()

        # These three operations may not be thread-safe, and workunits may run in separate threads
        # and thus end concurrently, so we want to lock these operations.
        with self._stats_lock:
            self.cumulative_timings.add_timing(path, duration, is_tool)
            self.self_timings.add_timing(path, self_time, is_tool)
            self.outcomes[path] = workunit.outcome_string(workunit.outcome())

    def get_critical_path_timings(self):
        """Get the cumulative timings of each goal and all of the goals it (transitively) depended
        on."""
        setup_workunit = WorkUnitLabel.SETUP.lower()
        transitive_dependencies = dict()
        raw_timings = dict()
        for entry in self.cumulative_timings.get_all():
            raw_timings[entry["label"]] = entry["timing"]

        critical_path_timings = AggregatedTimings()

        def add_to_timings(goal, dep):
            tracking_label = get_label(goal)
            timing_label = get_label(dep)
            critical_path_timings.add_timing(tracking_label, raw_timings.get(timing_label, 0.0))

        def get_label(dep):
            return f"{RunTracker.DEFAULT_ROOT_NAME}:{dep}"

        # Add setup workunit to critical_path_timings manually, as its unaccounted for, otherwise.
        add_to_timings(setup_workunit, setup_workunit)

        for goal, deps in transitive_dependencies.items():
            add_to_timings(goal, goal)
            for dep in deps:
                add_to_timings(goal, dep)

        return critical_path_timings

    def get_options_to_record(self) -> dict:
        recorded_options = {}
        scopes = self.options.stats_option_scopes_to_record
        if "*" in scopes:
            scopes = self._all_options.known_scope_to_info.keys()
        for scope in scopes:
            scope_and_maybe_option = scope.split("^")
            if scope == GLOBAL_SCOPE:
                scope = GLOBAL_SCOPE_CONFIG_SECTION
            recorded_options[scope] = self._get_option_to_record(*scope_and_maybe_option)
        return recorded_options

    def _get_option_to_record(self, scope, option=None):
        """Looks up an option scope (and optionally option therein) in the options parsed by Pants.

        Returns a dict of of all options in the scope, if option is None. Returns the specific
        option if option is not None. Raises ValueError if scope or option could not be found.
        """
        scope_to_look_up = scope if scope != GLOBAL_SCOPE_CONFIG_SECTION else ""
        try:
            value = self._all_options.for_scope(
                scope_to_look_up, inherit_from_enclosing_scope=False
            ).as_dict()
            if option is None:
                return value
            else:
                return value[option]
        except (Config.ConfigValidationError, AttributeError) as e:
            option_str = "" if option is None else f" option {option}"
            raise ValueError(
                f"Couldn't find option scope {scope}{option_str} for recording ({e!r})"
            )

    def retrieve_logs(self) -> List[str]:
        """Get a list of every log entry recorded during this run."""

        if not self.run_logs_file:
            return []

        output = []
        try:
            with open(self.run_logs_file, "r") as f:
                output = f.readlines()
        except OSError as e:
            logger.warning("Error retrieving per-run logs from RunTracker.", exc_info=e)

        return output
