# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import os
import sys
import time
import uuid
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, List, Optional

from pants.base.exiter import PANTS_SUCCEEDED_EXIT_CODE, ExitCode
from pants.base.run_info import RunInfo
from pants.engine.internals.native import Native
from pants.option.config import Config
from pants.option.options import Options
from pants.option.options_fingerprinter import CoercingOptionEncoder
from pants.option.scope import GLOBAL_SCOPE, GLOBAL_SCOPE_CONFIG_SECTION

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


class RunTracker:
    """Tracks and times the execution of a single Pants run."""

    def __init__(self, options: Options):
        """
        :API: public
        """
        self.native = Native()

        self._has_started: bool = False
        self._has_ended: bool = False

        # Select a globally unique ID for the run, that sorts by time.
        run_timestamp = time.time()
        run_uuid = uuid.uuid4().hex
        str_time = time.strftime("%Y_%m_%d_%H_%M_%S", time.localtime(run_timestamp))
        millis = int((run_timestamp * 1000) % 1000)
        self.run_id = f"pants_run_{str_time}_{millis}_{run_uuid}"

        self._all_options = options
        info_dir = os.path.join(self._all_options.for_global_scope().pants_workdir, "run-tracker")
        self._run_info_dir = os.path.join(info_dir, self.run_id)
        self._run_info = RunInfo(os.path.join(self._run_info_dir, "info"))

        # pantsd stats.
        self._pantsd_metrics: Dict[str, int] = dict()

        self.run_logs_file = Path(self._run_info_dir, "logs")
        self.native.set_per_run_log_path(str(self.run_logs_file))

        # Initialized in `start()`.
        self._run_start_time: Optional[float] = None
        self._run_total_duration: Optional[float] = None

    @property
    def goals(self) -> List[str]:
        return self._all_options.goals if self._all_options else []

    def start(self, run_start_time: float, specs: List[str]) -> None:
        """Start tracking this pants run."""
        if self._has_started:
            raise AssertionError("RunTracker.start must not be called multiple times.")
        self._has_started = True

        # Initialize the run.
        self._run_start_time = run_start_time
        self._run_info.add_basic_info(self.run_id, run_start_time)
        cmd_line = " ".join(["pants"] + sys.argv[1:])
        self._run_info.add_info("cmd_line", cmd_line)
        self._run_info.add_info("specs_from_command_line", specs, stringify=False)

    def set_pantsd_scheduler_metrics(self, metrics: Dict[str, int]) -> None:
        self._pantsd_metrics = metrics

    @property
    def pantsd_scheduler_metrics(self) -> Dict[str, int]:
        return dict(self._pantsd_metrics)  # defensive copy

    def run_information(self):
        """Basic information about this run."""
        return self._run_info.get_as_dict()

    def has_ended(self) -> bool:
        return self._has_ended

    def end_run(self, exit_code: ExitCode) -> None:
        """This pants run is over, so stop tracking it.

        Note: If end_run() has been called once, subsequent calls are no-ops.
        """

        if self.has_ended():
            return
        self._has_ended = True

        if self._run_start_time is None:
            raise Exception("RunTracker.end_run() called without calling .start()")

        duration = time.time() - self._run_start_time
        self._total_run_time = duration

        outcome_str = "SUCCESS" if exit_code == PANTS_SUCCEEDED_EXIT_CODE else "FAILURE"

        if self._run_info.get_info("outcome") is None:
            # If the goal is clean-all then the run info dir no longer exists, so ignore that error.
            self._run_info.add_info("outcome", outcome_str, ignore_errors=True)

        self.native.set_per_run_log_path(None)

    def get_cumulative_timings(self) -> List[Dict[str, Any]]:
        return [{"label": "main", "timing": self._total_run_time}]

    def get_options_to_record(self) -> dict:
        recorded_options = {}
        scopes = self._all_options.for_global_scope().stats_record_option_scopes
        if "*" in scopes:
            scopes = self._all_options.known_scope_to_info.keys() if self._all_options else []
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
