# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json
import logging
import os
import sys
import time
import uuid
from collections import OrderedDict
from pathlib import Path
from typing import Dict, List, Optional

from pants.base.run_info import RunInfo
from pants.base.workunit import WorkUnit
from pants.engine.internals.native import Native
from pants.goal.aggregated_timings import AggregatedTimings, TimingData
from pants.option.config import Config
from pants.option.options import Options
from pants.option.options_fingerprinter import CoercingOptionEncoder
from pants.option.scope import GLOBAL_SCOPE, GLOBAL_SCOPE_CONFIG_SECTION
from pants.option.subsystem import Subsystem
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
    options_scope = "run-tracker"
    help = "Tracks and times the execution of a pants run."

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
            default=["*"],
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

        run_timestamp = time.time()
        run_uuid = uuid.uuid4().hex
        str_time = time.strftime("%Y_%m_%d_%H_%M_%S", time.localtime(run_timestamp))
        millis = int((run_timestamp * 1000) % 1000)
        self.run_id = f"pants_run_{str_time}_{millis}_{run_uuid}"

        # Initialized in `initialize()`.
        self.run_info_dir = None
        self.run_info = None
        self.cumulative_timings = None

        # Initialized in `start()`.

        self._run_start_time = None
        self._all_options: Optional[Options] = None
        self._has_ended: bool = False
        self.native = Native()
        self.run_logs_file: Optional[Path] = None

    @property
    def goals(self) -> List[str]:
        return self._all_options.goals if self._all_options else []

    def start(self, all_options: Options, run_start_time: float) -> None:
        """Start tracking this pants run."""
        if self.run_info:
            raise AssertionError("RunTracker.start must not be called multiple times.")

        # Initialize the run.

        self._run_start_time = run_start_time

        info_dir = os.path.join(self.options.pants_workdir, self.options_scope)
        self.run_info_dir = os.path.join(info_dir, self.run_id)
        self.run_info = RunInfo(os.path.join(self.run_info_dir, "info"))
        self.run_info.add_basic_info(self.run_id, run_start_time)

        cmd_line = " ".join(["pants"] + sys.argv[1:])
        self.run_info.add_info("cmd_line", cmd_line)

        # Create a 'latest' symlink, after we add_infos, so we're guaranteed that the file exists.
        link_to_latest = os.path.join(os.path.dirname(self.run_info_dir), "latest")

        relative_symlink(self.run_info_dir, link_to_latest)

        # Time spent in a workunit, including its children.
        self.cumulative_timings = AggregatedTimings(
            os.path.join(self.run_info_dir, "cumulative_timings")
        )

        # pantsd stats.
        self._pantsd_metrics: Dict[str, int] = dict()

        self._all_options = all_options

        self.run_logs_file = Path(self.run_info_dir, "logs")
        self.native.set_per_run_log_path(str(self.run_logs_file))

    def set_pantsd_scheduler_metrics(self, metrics: Dict[str, int]) -> None:
        self._pantsd_metrics = metrics

    @property
    def pantsd_scheduler_metrics(self) -> Dict[str, int]:
        return dict(self._pantsd_metrics)  # defensive copy

    @classmethod
    def write_stats_to_json(cls, file_name: str, stats: dict) -> None:
        """Write stats to a local json file."""
        params = json.dumps(stats, cls=RunTrackerOptionEncoder)
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

    def store_stats(self) -> None:
        """Store stats about this run in local and optionally remote stats dbs."""

        stats = {
            "run_info": self.run_information(),
            "pantsd_stats": self.pantsd_scheduler_metrics,
            "cumulative_timings": self.get_cumulative_timings(),
            "recorded_options": self.get_options_to_record(),
        }

        # Write stats to user-defined json file.
        stats_json_file_name = self.options.stats_local_json_file
        if stats_json_file_name:
            self.write_stats_to_json(stats_json_file_name, stats)

    def has_ended(self) -> bool:
        return self._has_ended

    def end_run(self, outcome: int) -> None:
        """This pants run is over, so stop tracking it.

        Note: If end_run() has been called once, subsequent calls are no-ops.

        :return: PANTS_SUCCEEDED_EXIT_CODE or PANTS_FAILED_EXIT_CODE
        """

        if self.has_ended():
            return

        self._has_ended = True

        if self._run_start_time is None:
            raise Exception("RunTracker.end_run() called without calling .start()")

        duration = time.time() - self._run_start_time

        self.cumulative_timings.add_timing(label="main", secs=duration)

        outcome_str = WorkUnit.outcome_string(outcome)

        if self.run_info.get_info("outcome") is None:
            # If the goal is clean-all then the run info dir no longer exists, so ignore that error.
            self.run_info.add_info("outcome", outcome_str, ignore_errors=True)

        self.store_stats()

        self.native.set_per_run_log_path(None)

        return

    def get_cumulative_timings(self) -> TimingData:
        return self.cumulative_timings.get_all()  # type: ignore[no-any-return]

    def get_options_to_record(self) -> dict:
        recorded_options = {}
        scopes = self.options.stats_option_scopes_to_record
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
