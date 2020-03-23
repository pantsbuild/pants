# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import ast
import copy
import json
import multiprocessing
import os
import sys
import threading
import time
import uuid
from collections import OrderedDict
from contextlib import contextmanager
from typing import Any, Dict, Optional

import requests

from pants.auth.basic_auth import BasicAuth
from pants.base.exiter import PANTS_FAILED_EXIT_CODE, PANTS_SUCCEEDED_EXIT_CODE
from pants.base.run_info import RunInfo
from pants.base.worker_pool import SubprocPool, WorkerPool
from pants.base.workunit import WorkUnit, WorkUnitLabel
from pants.goal.aggregated_timings import AggregatedTimings
from pants.goal.artifact_cache_stats import ArtifactCacheStats
from pants.goal.pantsd_stats import PantsDaemonStats
from pants.option.config import Config
from pants.option.options_fingerprinter import CoercingOptionEncoder
from pants.reporting.json_reporter import JsonReporter
from pants.reporting.report import Report
from pants.subsystem.subsystem import Subsystem
from pants.util.dirutil import relative_symlink, safe_file_dump
from pants.version import VERSION


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
    """Tracks and times the execution of a pants run.

    Also manages background work.

    Use like this:

    run_tracker.start()
    with run_tracker.new_workunit('compile'):
      with run_tracker.new_workunit('java'):
        ...
      with run_tracker.new_workunit('scala'):
        ...
    run_tracker.close()

    Can track execution against multiple 'roots', e.g., one for the main thread and another for
    background threads.

    :API: public
    """

    options_scope = "run-tracker"

    # The name of the tracking root for the main thread (and the foreground worker threads).
    DEFAULT_ROOT_NAME = "main"

    # The name of the tracking root for the background worker threads.
    BACKGROUND_ROOT_NAME = "background"
    SUPPORTED_STATS_VERSIONS = [1, 2]

    @classmethod
    def subsystem_dependencies(cls):
        return super().subsystem_dependencies() + (BasicAuth,)

    @classmethod
    def register_options(cls, register):
        register(
            "--stats-upload-urls",
            advanced=True,
            type=dict,
            default={},
            help="Upload stats to these URLs on run completion.  Value is a map from URL to the "
            "name of the auth provider the user must auth against in order to upload stats "
            "to that URL, or None/empty string if no auth is required.  Currently the "
            "auth provider name is only used to provide a more helpful error message.",
        )
        register(
            "--stats-upload-timeout",
            advanced=True,
            type=int,
            default=2,
            help="Wait at most this many seconds for the stats upload to complete.",
        )
        register(
            "--stats-version",
            advanced=True,
            type=int,
            default=1,
            choices=cls.SUPPORTED_STATS_VERSIONS,
            help="Format of stats JSON for uploads and local json file.",
        )
        register(
            "--num-foreground-workers",
            advanced=True,
            type=int,
            default=multiprocessing.cpu_count(),
            help="Number of threads for foreground work.",
        )
        register(
            "--num-background-workers",
            advanced=True,
            type=int,
            default=multiprocessing.cpu_count(),
            help="Number of threads for background work.",
        )
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
            "i.e. to get option enable_pantsd in the GLOBAL scope, you'd pass "
            "GLOBAL^enable_pantsd",
        )

    def __init__(self, *args, **kwargs):
        """
        :API: public
        """
        super().__init__(*args, **kwargs)
        self._run_timestamp = time.time()
        self._cmd_line = " ".join(["pants"] + sys.argv[1:])
        self._sorted_goal_infos = tuple()
        self._v2_goal_rule_names = tuple()

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
        self.artifact_cache_stats = None
        self.pantsd_stats = None

        # Initialized in `start()`.
        self.report = None
        self.json_reporter = None
        self._main_root_workunit = None
        self._all_options = None

        # A lock to ensure that adding to stats at the end of a workunit
        # operates thread-safely.
        self._stats_lock = threading.Lock()

        # Log of success/failure/aborted for each workunit.
        self.outcomes = {}

        # Number of threads for foreground work.
        self._num_foreground_workers = self.get_options().num_foreground_workers

        # Number of threads for background work.
        self._num_background_workers = self.get_options().num_background_workers

        # self._threadlocal.current_workunit contains the current workunit for the calling thread.
        # Note that multiple threads may share a name (e.g., all the threads in a pool).
        self._threadlocal = threading.local()

        # A logger facade that logs into this RunTracker.
        self._logger = RunTrackerLogger(self)

        # For background work.  Created lazily if needed.
        self._background_worker_pool = None
        self._background_root_workunit = None

        # Trigger subproc pool init while our memory image is still clean (see SubprocPool docstring).
        SubprocPool.set_num_processes(self._num_foreground_workers)
        SubprocPool.foreground()

        self._aborted = False

        # Data will be organized first by target and then scope.
        # Eg:
        # {
        #   'target/address:name': {
        #     'running_scope': {
        #       'run_duration': 356.09
        #     },
        #     'GLOBAL': {
        #       'target_type': 'pants.test'
        #     }
        #   }
        # }
        self._target_to_data = {}

        self._end_memoized_result = None

    def set_sorted_goal_infos(self, sorted_goal_infos):
        self._sorted_goal_infos = sorted_goal_infos

    def set_v2_goal_rule_names(self, v2_goal_rule_names):
        self._v2_goal_rule_names = v2_goal_rule_names

    def register_thread(self, parent_workunit):
        """Register the parent workunit for all work in the calling thread.

        Multiple threads may have the same parent (e.g., all the threads in a pool).
        """
        self._threadlocal.current_workunit = parent_workunit

    def is_under_background_root(self, workunit):
        """Is the workunit running under the background thread's root."""
        return workunit.is_background(self._background_root_workunit)

    def is_main_root_workunit(self, workunit):
        return workunit is self._main_root_workunit

    def is_background_root_workunit(self, workunit):
        return workunit is self._background_root_workunit

    def initialize(self, all_options):
        """Create run_info and relevant directories, and return the run id.

        Must be called before `start`.
        """
        if self.run_info:
            raise AssertionError("RunTracker.initialize must not be called multiple times.")

        # Initialize the run.

        info_dir = os.path.join(self.get_options().pants_workdir, self.options_scope)
        self.run_info_dir = os.path.join(info_dir, self.run_id)
        self.run_info = RunInfo(os.path.join(self.run_info_dir, "info"))
        self.run_info.add_basic_info(self.run_id, self._run_timestamp)
        self.run_info.add_info("cmd_line", self._cmd_line)
        if self.get_options().parent_build_id:
            self.run_info.add_info("parent_build_id", self.get_options().parent_build_id)

        # Create a 'latest' symlink, after we add_infos, so we're guaranteed that the file exists.
        link_to_latest = os.path.join(os.path.dirname(self.run_info_dir), "latest")

        relative_symlink(self.run_info_dir, link_to_latest)

        # Time spent in a workunit, including its children.
        self.cumulative_timings = AggregatedTimings(
            os.path.join(self.run_info_dir, "cumulative_timings")
        )

        # Time spent in a workunit, not including its children.
        self.self_timings = AggregatedTimings(os.path.join(self.run_info_dir, "self_timings"))

        # Hit/miss stats for the artifact cache.
        self.artifact_cache_stats = ArtifactCacheStats(
            os.path.join(self.run_info_dir, "artifact_cache_stats")
        )

        # Daemon stats.
        self.pantsd_stats = PantsDaemonStats()

        self._all_options = all_options

        return (self.run_id, self.run_uuid)

    def start(self, report, run_start_time=None):
        """Start tracking this pants run using the given Report.

        `RunTracker.initialize` must have been called first to create the run_info_dir and
        run_info. TODO: This lifecycle represents a delicate dance with the `Reporting.initialize`
        method, and portions of the `RunTracker` should likely move to `Reporting` instead.

        report: an instance of pants.reporting.Report.
        """
        if not self.run_info:
            raise AssertionError("RunTracker.initialize must be called before RunTracker.start.")

        self.report = report

        # Set up the JsonReporter for V2 stats.
        if self._stats_version == 2:
            json_reporter_settings = JsonReporter.Settings(log_level=Report.INFO)
            self.json_reporter = JsonReporter(self, json_reporter_settings)
            report.add_reporter("json", self.json_reporter)

        self.report.open()

        # And create the workunit.
        self._main_root_workunit = WorkUnit(
            run_info_dir=self.run_info_dir, parent=None, name=RunTracker.DEFAULT_ROOT_NAME, cmd=None
        )
        self.register_thread(self._main_root_workunit)
        # Set the true start time in the case of e.g. the daemon.
        self._main_root_workunit.start(run_start_time)
        self.report.start_workunit(self._main_root_workunit)

        # Log reporting details.
        url = self.run_info.get_info("report_url")
        if url:
            self.log(Report.INFO, f"See a report at: {url}")
        else:
            self.log(Report.INFO, "(To run a reporting server: ./pants server)")

    def set_root_outcome(self, outcome):
        """Useful for setup code that doesn't have a reference to a workunit."""
        self._main_root_workunit.set_outcome(outcome)

    @property
    def logger(self):
        return self._logger

    @contextmanager
    def new_workunit(self, name, labels=None, cmd="", log_config=None):
        """Creates a (hierarchical) subunit of work for the purpose of timing and reporting.

        - name: A short name for this work. E.g., 'resolve', 'compile', 'scala', 'zinc'.
        - labels: An optional iterable of labels. The reporters can use this to decide how to
                  display information about this work.
        - cmd: An optional longer string representing this work.
               E.g., the cmd line of a compiler invocation.
        - log_config: An optional tuple WorkUnit.LogConfig of task-level options affecting reporting.

        Use like this:

        with run_tracker.new_workunit(name='compile', labels=[WorkUnitLabel.TASK]) as workunit:
          <do scoped work here>
          <set the outcome on workunit if necessary>

        Note that the outcome will automatically be set to failure if an exception is raised
        in a workunit, and to success otherwise, so usually you only need to set the
        outcome explicitly if you want to set it to warning.

        :API: public
        """
        parent = self._threadlocal.current_workunit
        with self.new_workunit_under_parent(
            name, parent=parent, labels=labels, cmd=cmd, log_config=log_config
        ) as workunit:
            self._threadlocal.current_workunit = workunit
            try:
                yield workunit
            finally:
                self._threadlocal.current_workunit = parent

    @contextmanager
    def new_workunit_under_parent(self, name, parent, labels=None, cmd="", log_config=None):
        """Creates a (hierarchical) subunit of work for the purpose of timing and reporting.

        - name: A short name for this work. E.g., 'resolve', 'compile', 'scala', 'zinc'.
        - parent: The new workunit is created under this parent.
        - labels: An optional iterable of labels. The reporters can use this to decide how to
                  display information about this work.
        - cmd: An optional longer string representing this work.
               E.g., the cmd line of a compiler invocation.

        Task code should not typically call this directly.

        :API: public
        """
        workunit = WorkUnit(
            run_info_dir=self.run_info_dir,
            parent=parent,
            name=name,
            labels=labels,
            cmd=cmd,
            log_config=log_config,
        )
        workunit.start()

        outcome = WorkUnit.FAILURE  # Default to failure we will override if we get success/abort.
        try:
            self.report.start_workunit(workunit)
            yield workunit
        except KeyboardInterrupt:
            outcome = WorkUnit.ABORTED
            self._aborted = True
            raise
        else:
            outcome = WorkUnit.SUCCESS
        finally:
            workunit.set_outcome(outcome)
            self.end_workunit(workunit)

    @property
    def _stats_version(self) -> int:
        stats_version: int = self.get_options().stats_version
        return stats_version

    def log(self, level, *msg_elements):
        """Log a message against the current workunit."""
        self.report.log(self._threadlocal.current_workunit, level, *msg_elements)

    @classmethod
    def _get_headers(cls, stats_version: int) -> Dict[str, str]:
        return {
            "User-Agent": f"pants/v{VERSION}",
            "X-Pants-Stats-Version": str(stats_version),
        }

    @classmethod
    def post_stats(
        cls,
        stats_url: str,
        stats: Dict[str, Any],
        timeout: int = 2,
        auth_provider: Optional[str] = None,
        stats_version: int = 1,
    ):
        """POST stats to the given url.

        :return: True if upload was successful, False otherwise.
        """

        def error(msg):
            # Report aleady closed, so just print error.
            print(f"WARNING: Failed to upload stats to {stats_url} due to {msg}", file=sys.stderr)
            return False

        if stats_version not in cls.SUPPORTED_STATS_VERSIONS:
            raise ValueError("Invalid stats version")

        auth_data = BasicAuth.global_instance().get_auth_for_provider(auth_provider)
        headers = cls._get_headers(stats_version=stats_version)
        headers.update(auth_data.headers)

        if stats_version == 2:
            params = cls._json_dump_options({"builds": [stats]})
            headers["Content-Type"] = "application/json"
        else:
            # TODO(benjy): The upload protocol currently requires separate top-level params, with JSON
            # values.  Probably better for there to be one top-level JSON value, namely json.dumps(stats).
            # But this will first require changing the upload receiver at every shop that uses this.
            params = {k: cls._json_dump_options(v) for (k, v) in stats.items()}  # type: ignore[assignment]

        # We can't simply let requests handle redirects, as we only allow them for specific codes:
        # 307 and 308 indicate that the redirected request must use the same method, POST in this case.
        # So they indicate a true redirect of the POST itself, and we allow them.
        # The other redirect codes either must, or in practice do, cause the user agent to switch the
        # method to GET. So when they are encountered on a POST, it indicates an auth problem (a
        # redirection to a login page).
        def do_post(url, num_redirects_allowed):
            if num_redirects_allowed < 0:
                return error("too many redirects.")
            res = requests.post(
                url,
                data=params,
                timeout=timeout,
                headers=headers,
                allow_redirects=False,
                **auth_data.request_args,
            )
            if res.status_code in {307, 308}:
                return do_post(res.headers["location"], num_redirects_allowed - 1)
            elif 300 <= res.status_code < 400 or res.status_code == 401:
                error(f"HTTP error code: {res.status_code}. Reason: {res.reason}.")
                print(
                    f"Use `path/to/pants login --to={auth_provider}` to authenticate "
                    "against the stats upload service.",
                    file=sys.stderr,
                )
                return False
            elif not res.ok:
                error(f"HTTP error code: {res.status_code}. Reason: {res.reason}.")
                return False
            return True

        try:
            return do_post(stats_url, num_redirects_allowed=6)
        except Exception as e:  # Broad catch - we don't want to fail the build over upload errors.
            return error(f"Error: {e!r}")

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
        target_data = run_information.get("target_data", None)
        if target_data:
            run_information["target_data"] = ast.literal_eval(target_data)
        return run_information

    def _stats(self) -> dict:
        stats = {
            "run_info": self.run_information(),
            "artifact_cache_stats": self.artifact_cache_stats.get_all(),
            "pantsd_stats": self.pantsd_stats.get_all(),
            "cumulative_timings": self.cumulative_timings.get_all(),
            "recorded_options": self._get_options_to_record(),
        }
        if self._stats_version == 2:
            stats["workunits"] = self.json_reporter.results
        else:
            stats.update(
                {
                    "self_timings": self.self_timings.get_all(),
                    "critical_path_timings": self.get_critical_path_timings().get_all(),
                    "outcomes": self.outcomes,
                }
            )
        return stats

    def store_stats(self):
        """Store stats about this run in local and optionally remote stats dbs."""
        stats = self._stats()

        # Write stats to user-defined json file.
        stats_json_file_name = self.get_options().stats_local_json_file
        if stats_json_file_name:
            self.write_stats_to_json(stats_json_file_name, stats)

        # Upload to remote stats db.
        stats_upload_urls = copy.copy(self.get_options().stats_upload_urls)
        timeout = self.get_options().stats_upload_timeout
        for stats_url, auth_provider in stats_upload_urls.items():
            self.post_stats(
                stats_url,
                stats,
                timeout=timeout,
                auth_provider=auth_provider,
                stats_version=self._stats_version,
            )

    _log_levels = [Report.ERROR, Report.ERROR, Report.WARN, Report.INFO, Report.INFO]

    def has_ended(self) -> bool:
        return self._end_memoized_result is not None

    def end(self):
        """This pants run is over, so stop tracking it.

        Note: If end() has been called once, subsequent calls are no-ops.

        :return: PANTS_SUCCEEDED_EXIT_CODE or PANTS_FAILED_EXIT_CODE
        """
        if self._end_memoized_result is not None:
            return self._end_memoized_result
        if self._background_worker_pool:
            if self._aborted:
                self.log(Report.INFO, "Aborting background workers.")
                self._background_worker_pool.abort()
            else:
                self.log(Report.INFO, "Waiting for background workers to finish.")
                self._background_worker_pool.shutdown()
            self.end_workunit(self._background_root_workunit)

        self.shutdown_worker_pool()

        # Run a dummy work unit to write out one last timestamp.
        with self.new_workunit("complete"):
            pass

        self.end_workunit(self._main_root_workunit)

        outcome = self._main_root_workunit.outcome()
        if self._background_root_workunit:
            outcome = min(outcome, self._background_root_workunit.outcome())
        outcome_str = WorkUnit.outcome_string(outcome)
        log_level = RunTracker._log_levels[outcome]
        self.log(log_level, outcome_str)

        if self.run_info.get_info("outcome") is None:
            # If the goal is clean-all then the run info dir no longer exists, so ignore that error.
            self.run_info.add_info("outcome", outcome_str, ignore_errors=True)

        if self._sorted_goal_infos and self.run_info.get_info("computed_goals") is None:
            self.run_info.add_info(
                "computed_goals",
                self._v2_goal_rule_names
                + tuple(goal.goal.name for goal in self._sorted_goal_infos),
                stringify=False,
                # If the goal is clean-all then the run info dir no longer exists, so ignore that error.
                ignore_errors=True,
            )

        if self._target_to_data:
            self.run_info.add_info("target_data", self._target_to_data)

        self.report.close()
        self.store_stats()

        run_failed = outcome in [WorkUnit.FAILURE, WorkUnit.ABORTED]
        result = PANTS_FAILED_EXIT_CODE if run_failed else PANTS_SUCCEEDED_EXIT_CODE
        self._end_memoized_result = result
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
        for goal_info in self._sorted_goal_infos:
            deps = transitive_dependencies.setdefault(goal_info.goal.name, set())
            for dep in goal_info.goal_dependencies:
                deps.add(dep.name)
                deps.update(transitive_dependencies.get(dep.name))
            # Add setup workunit as a dep manually, as its unaccounted for, otherwise.
            deps.add(setup_workunit)
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

    def get_background_root_workunit(self):
        if self._background_root_workunit is None:
            self._background_root_workunit = WorkUnit(
                run_info_dir=self.run_info_dir,
                parent=self._main_root_workunit,
                name="background",
                cmd=None,
            )
            self._background_root_workunit.start()
            self.report.start_workunit(self._background_root_workunit)
        return self._background_root_workunit

    def background_worker_pool(self):
        if self._background_worker_pool is None:  # Initialize lazily.
            self._background_worker_pool = WorkerPool(
                parent_workunit=self.get_background_root_workunit(),
                run_tracker=self,
                num_workers=self._num_background_workers,
                thread_name_prefix="background",
            )
        return self._background_worker_pool

    def shutdown_worker_pool(self):
        """Shuts down the SubprocPool.

        N.B. This exists only for internal use and to afford for fork()-safe operation in pantsd.
        """
        SubprocPool.shutdown(self._aborted)

    def _get_options_to_record(self) -> dict:
        recorded_options = {}
        for scope in self.get_options().stats_option_scopes_to_record:
            scope_and_maybe_option = scope.split("^")
            recorded_options[scope] = self._get_option_to_record(*scope_and_maybe_option)
        return recorded_options

    def _get_option_to_record(self, scope, option=None):
        """Looks up an option scope (and optionally option therein) in the options parsed by Pants.

        Returns a dict of of all options in the scope, if option is None. Returns the specific
        option if option is not None. Raises ValueError if scope or option could not be found.
        """
        scope_to_look_up = scope if scope != "GLOBAL" else ""
        try:
            value = self._all_options.for_scope(
                scope_to_look_up, inherit_from_enclosing_scope=False, include_passive_options=True
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

    @classmethod
    def _create_dict_with_nested_keys_and_val(cls, keys, value):
        """Recursively constructs a nested dictionary with the keys pointing to the value.

        For example:
        Given the list of keys ['a', 'b', 'c', 'd'] and a primitive
        value 'hello world', the method will produce the nested dictionary
        {'a': {'b': {'c': {'d': 'hello world'}}}}. The number of keys in the list
        defines the depth of the nested dict. If the list of keys is ['a'] and
        the value is 'hello world', then the result would be {'a': 'hello world'}.

        :param list of string keys: A list of keys to be nested as a dictionary.
        :param primitive value: The value of the information being stored.
        :return: dict of nested keys leading to the value.
        """

        if len(keys) > 1:
            new_keys = keys[:-1]
            new_val = {keys[-1]: value}
            return cls._create_dict_with_nested_keys_and_val(new_keys, new_val)
        elif len(keys) == 1:
            return {keys[0]: value}
        else:
            raise ValueError("Keys must contain at least one key.")

    @classmethod
    def _merge_list_of_keys_into_dict(cls, data, keys, value, index=0):
        """Recursively merge list of keys that points to the given value into data.

        Will override a primitive value with another primitive value, but will not
        override a primitive with a dictionary.

        For example:
        Given the dictionary {'a': {'b': {'c': 1}}, {'x': {'y': 100}}}, the keys
        ['a', 'b', 'd'] and the value 2, the updated dictionary would be
        {'a': {'b': {'c': 1, 'd': 2}}, {'x': {'y': 100}}}. Given this newly updated
        dictionary, the keys ['a', 'x', 'y', 'z'] and the value 200, the method would raise
        an error because we would be trying to override the primitive value 100 with the
        dict {'z': 200}.

        :param dict data: Dictionary to be updated.
        :param list of string keys: The keys that point to where the value should be stored.
               Will recursively find the correct place to store in the nested dicts.
        :param primitive value: The value of the information being stored.
        :param int index: The index into the list of keys (starting from the beginning).
        """
        if len(keys) == 0 or index < 0 or index >= len(keys):
            raise ValueError(
                "Keys must contain at least one key and index must be"
                "an integer greater than 0 and less than the number of keys."
            )
        if len(keys) < 2 or not data:
            new_data_to_add = cls._create_dict_with_nested_keys_and_val(keys, value)
            data.update(new_data_to_add)

        this_keys_contents = data.get(keys[index])
        if this_keys_contents:
            if isinstance(this_keys_contents, dict):
                cls._merge_list_of_keys_into_dict(this_keys_contents, keys, value, index + 1)
            elif index < len(keys) - 1:
                raise ValueError("Keys must point to a dictionary.")
            else:
                data[keys[index]] = value
        else:
            new_keys = keys[index:]
            new_data_to_add = cls._create_dict_with_nested_keys_and_val(new_keys, value)
            data.update(new_data_to_add)

    def report_target_info(self, scope, target, keys, val):
        """Add target information to run_info under target_data.

        Will Recursively construct a nested dict with the keys provided.

        Primitive values can be overwritten with other primitive values,
        but a primitive value cannot be overwritten with a dictionary.

        For example:
        Where the dictionary being updated is {'a': {'b': 16}}, reporting the value
        15 with the key list ['a', 'b'] will result in {'a': {'b':15}};
        but reporting the value 20 with the key list ['a', 'b', 'c'] will throw
        an error.

        :param string scope: The scope for which we are reporting the information.
        :param target: The target for which we want to store information.
        :type target: :class:`pants.build_graph.target.Target`
        :param list of string keys: The keys that will be recursively
               nested and pointing to the information being stored.
        :param primitive val: The value of the information being stored.

        :API: public
        """
        new_key_list = [target.address.spec, scope]
        new_key_list += keys
        self._merge_list_of_keys_into_dict(self._target_to_data, new_key_list, val, 0)


class RunTrackerLogger:
    """A logger facade that logs into a run tracker."""

    def __init__(self, run_tracker):
        self._run_tracker = run_tracker

    def debug(self, *msg_elements):
        self._run_tracker.log(Report.DEBUG, *msg_elements)

    def info(self, *msg_elements):
        self._run_tracker.log(Report.INFO, *msg_elements)

    def warn(self, *msg_elements):
        self._run_tracker.log(Report.WARN, *msg_elements)

    def error(self, *msg_elements):
        self._run_tracker.log(Report.ERROR, *msg_elements)
