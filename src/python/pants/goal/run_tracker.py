# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
import platform
import socket
import time
import uuid
from hashlib import sha256
from pathlib import Path
from typing import Any

from pants.base.build_environment import get_buildroot
from pants.base.exiter import PANTS_SUCCEEDED_EXIT_CODE, ExitCode
from pants.engine.internals import native_engine
from pants.option.errors import ConfigValidationError
from pants.option.options import Options
from pants.option.scope import GLOBAL_SCOPE, GLOBAL_SCOPE_CONFIG_SECTION
from pants.util.osutil import getuser
from pants.version import VERSION

logger = logging.getLogger(__name__)


class RunTracker:
    """Tracks and times the execution of a single Pants run."""

    # TODO: Find a way to know from a goal name whether it's a standard or a custom
    #  goal whose name could, in theory, reveal something proprietary. That's more work than
    #  we want to do at the moment, so we maintain this manual list for now.
    STANDARD_GOALS = frozenset(
        (
            "check",
            "count-loc",
            "dependents",
            "dependencies",
            "export-codegen",
            "filedeps",
            "fmt",
            "lint",
            "list",
            "package",
            "py-constraints",
            "repl",
            "roots",
            "run",
            "tailor",
            "test",
            "typecheck",
            "validate",
        )
    )

    def __init__(self, args: tuple[str, ...], options: Options):
        """
        :API: public
        """
        self._has_started: bool = False
        self._has_ended: bool = False

        # Select a globally unique ID for the run, that sorts by time.
        run_timestamp = time.time()
        run_uuid = uuid.uuid4().hex
        str_time = time.strftime("%Y_%m_%d_%H_%M_%S", time.localtime(run_timestamp))
        millis = int((run_timestamp * 1000) % 1000)
        self.run_id = f"pants_run_{str_time}_{millis}_{run_uuid}"

        self._args = args
        self._all_options = options
        info_dir = Path(self._all_options.for_global_scope().pants_workdir) / "run-tracker"
        self._run_info: dict[str, Any] = {}

        # pantsd stats.
        self._pantsd_metrics: dict[str, int] = dict()

        self.run_logs_file = info_dir / self.run_id / "logs"
        self.run_logs_file.parent.mkdir(exist_ok=True, parents=True)
        native_engine.set_per_run_log_path(str(self.run_logs_file))

        # Initialized in `start()`.
        self._run_start_time: float | None = None
        self._run_total_duration: float | None = None

    @property
    def goals(self) -> list[str]:
        return self._all_options.goals if self._all_options else []

    @property
    def active_standard_backends(self) -> list[str]:
        return [
            backend
            for backend in self._all_options.for_global_scope().backend_packages
            if backend.startswith("pants.backend.")
        ]

    def start(self, run_start_time: float, specs: list[str]) -> None:
        """Start tracking this pants run."""
        if self._has_started:
            raise AssertionError("RunTracker.start must not be called multiple times.")
        self._has_started = True

        # Initialize the run.
        self._run_start_time = run_start_time

        datetime = time.strftime("%A %b %d, %Y %H:%M:%S", time.localtime(run_start_time))
        cmd_line = " ".join(("pants",) + self._args[1:])

        self._run_info.update(
            {
                "id": self.run_id,
                "timestamp": run_start_time,
                "datetime": datetime,
                "user": getuser(),
                "machine": socket.gethostname(),
                "buildroot": get_buildroot(),
                "path": get_buildroot(),
                "version": VERSION,
                "cmd_line": cmd_line,
                "specs_from_command_line": specs,
            }
        )

    def get_anonymous_telemetry_data(self, unhashed_repo_id: str) -> dict[str, str | list[str]]:
        def maybe_hash_with_repo_id_prefix(s: str) -> str:
            qualified_str = f"{unhashed_repo_id}.{s}" if s else unhashed_repo_id
            # If the repo_id is the empty string we return a blank string.
            return sha256(qualified_str.encode()).hexdigest() if unhashed_repo_id else ""

        return {
            "run_id": str(self._run_info.get("id", uuid.uuid4())),
            "timestamp": str(self._run_info.get("timestamp")),
            # Note that this method is called after the StreamingWorkunitHandler.session() ends,
            # i.e., after end_run() has been called, so duration will be set.
            "duration": str(self._run_total_duration),
            "outcome": str(self._run_info.get("outcome")),
            "platform": platform.platform(),
            "python_implementation": platform.python_implementation(),
            "python_version": platform.python_version(),
            "pants_version": str(self._run_info.get("version")),
            # Note that if repo_id is the empty string then these three fields will be empty.
            "repo_id": maybe_hash_with_repo_id_prefix(""),
            "machine_id": maybe_hash_with_repo_id_prefix(str(uuid.getnode())),
            "user_id": maybe_hash_with_repo_id_prefix(getuser()),
            # Note that we conserve the order in which the goals were specified on the cmd line.
            "standard_goals": [goal for goal in self.goals if goal in self.STANDARD_GOALS],
            # Lets us know of any custom goals were used, without knowing their names.
            "num_goals": str(len(self.goals)),
            "active_standard_backends": sorted(self.active_standard_backends),
        }

    def set_pantsd_scheduler_metrics(self, metrics: dict[str, int]) -> None:
        self._pantsd_metrics = metrics

    @property
    def pantsd_scheduler_metrics(self) -> dict[str, int]:
        return dict(self._pantsd_metrics)  # defensive copy

    def run_information(self) -> dict[str, Any]:
        """Basic information about this run."""
        return self._run_info

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
        self._run_total_duration = duration

        outcome_str = "SUCCESS" if exit_code == PANTS_SUCCEEDED_EXIT_CODE else "FAILURE"
        self._run_info["outcome"] = outcome_str

        native_engine.set_per_run_log_path(None)

    def get_cumulative_timings(self) -> list[dict[str, Any]]:
        return [{"label": "main", "timing": self._run_total_duration}]

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
                scope_to_look_up, check_deprecations=False
            ).as_dict()
            if option is None:
                return value
            else:
                return value[option]
        except (ConfigValidationError, AttributeError) as e:
            option_str = "" if option is None else f" option {option}"
            raise ValueError(
                f"Couldn't find option scope {scope}{option_str} for recording ({e!r})"
            )

    def retrieve_logs(self) -> list[str]:
        """Get a list of every log entry recorded during this run."""

        if not self.run_logs_file:
            return []

        output = []
        try:
            with open(self.run_logs_file) as f:
                output = f.readlines()
        except OSError as e:
            logger.warning("Error retrieving per-run logs from RunTracker.", exc_info=e)

        return output

    @property
    def counter_names(self) -> tuple[str, ...]:
        return tuple(native_engine.all_counter_names())
