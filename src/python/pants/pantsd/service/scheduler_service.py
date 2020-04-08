# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import os
import queue
import threading
import time
from typing import List, Optional, Set

from pants.base.exiter import PANTS_SUCCEEDED_EXIT_CODE
from pants.base.specs import Specs
from pants.engine.fs import PathGlobs, Snapshot
from pants.engine.rules import UnionMembership
from pants.goal.run_tracker import RunTracker
from pants.init.engine_initializer import LegacyGraphScheduler, LegacyGraphSession
from pants.option.options import Options
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.pantsd.service.fs_event_service import FSEventService
from pants.pantsd.service.pants_service import PantsService


class SchedulerService(PantsService):
    """The pantsd scheduler service.

    This service holds an online Scheduler instance that is primed via watchman filesystem events.
    """

    QUEUE_SIZE = 64
    INVALIDATION_WATCHER_LIVENESS_CHECK_INTERVAL = 1

    def __init__(
        self,
        *,
        fs_event_service: Optional[FSEventService],
        legacy_graph_scheduler: LegacyGraphScheduler,
        build_root: str,
        invalidation_globs: List[str],
        pantsd_pidfile: Optional[str],
        union_membership: UnionMembership,
    ) -> None:
        """
        :param fs_event_service: An unstarted FSEventService instance for setting up filesystem event handlers.
        :param legacy_graph_scheduler: The LegacyGraphScheduler instance for graph construction.
        :param build_root: The current build root.
        :param invalidation_globs: A list of `globs` that when encountered in filesystem event
                                   subscriptions will tear down the daemon.
        :param pantsd_pidfile: The path to the pantsd pidfile for fs event monitoring.
        """
        super().__init__()
        self._fs_event_service = fs_event_service
        self._graph_helper = legacy_graph_scheduler
        self._invalidation_globs = invalidation_globs
        self._build_root = build_root
        self._pantsd_pidfile = pantsd_pidfile
        self._union_membership = union_membership

        self._scheduler = legacy_graph_scheduler.scheduler
        # This session is only used for checking whether any invalidation globs have been invalidated.
        # It is not involved with a build itself; just with deciding when we should restart pantsd.
        self._scheduler_session = self._scheduler.new_session(
            zipkin_trace_v2=False, build_id="scheduler_service_session",
        )
        self._logger = logging.getLogger(__name__)
        self._event_queue: queue.Queue = queue.Queue(maxsize=self.QUEUE_SIZE)
        self._watchman_is_running = threading.Event()
        self._invalidating_snapshot = None
        self._invalidating_files: Set[str] = set()

        self._loop_condition = LoopCondition()

    def _get_snapshot(self):
        """Returns a Snapshot of the input globs."""
        return self._scheduler_session.product_request(
            Snapshot, subjects=[PathGlobs(self._invalidation_globs)]
        )[0]

    def setup(self, services):
        """Service setup."""
        super().setup(services)
        # Register filesystem event handlers on an FSEventService instance.
        if self._fs_event_service is not None:
            self._fs_event_service.register_all_files_handler(
                self._enqueue_fs_event, self._fs_event_service.PANTS_ALL_FILES_SUBSCRIPTION_NAME
            )

        # N.B. We compute the invalidating fileset eagerly at launch with an assumption that files
        # that exist at startup are the only ones that can affect the running daemon.
        if self._fs_event_service is not None:
            if self._invalidation_globs:
                self._invalidating_snapshot = self._get_snapshot()
                self._invalidating_files = self._invalidating_snapshot.files
                self._logger.info(
                    "watching invalidating files: {}".format(self._invalidating_files)
                )

            if self._pantsd_pidfile:
                self._fs_event_service.register_pidfile_handler(
                    self._pantsd_pidfile, self._enqueue_fs_event
                )

    def _enqueue_fs_event(self, event):
        """Watchman filesystem event handler for BUILD/requirements.txt updates.

        Called via a thread.
        """
        self._logger.info(
            "enqueuing {} changes for subscription {}".format(
                len(event["files"]), event["subscription"]
            )
        )
        self._event_queue.put(event)

    def _maybe_invalidate_scheduler_batch(self):
        new_snapshot = self._get_snapshot()
        if (
            self._invalidating_snapshot
            and new_snapshot.directory_digest != self._invalidating_snapshot.directory_digest
        ):
            self._logger.critical(
                "saw file events covered by invalidation globs [{}], terminating the daemon.".format(
                    self._invalidating_files
                )
            )
            self.terminate()

    def _maybe_invalidate_scheduler_pidfile(self):
        new_pid = self._check_pid_changed()
        if new_pid is not False:
            self._logger.critical(
                "{} says pantsd PID is {} but my PID is: {}: terminating".format(
                    self._pantsd_pidfile, new_pid, os.getpid(),
                )
            )
            self.terminate()

    def _check_pid_changed(self):
        """Reads pidfile and returns False if its PID is ours, else a printable (maybe falsey)
        value."""
        try:
            with open(os.path.join(self._build_root, self._pantsd_pidfile), "r") as f:
                pid_from_file = f.read()
        except IOError:
            return "[no file could be read]"
        if int(pid_from_file) != os.getpid():
            return pid_from_file
        else:
            return False

    def _handle_batch_event(self, files):
        self._logger.debug("handling change event for: %s", files)

        invalidated = self._scheduler.invalidate_files(files)
        if invalidated:
            self._loop_condition.notify_all()

        self._maybe_invalidate_scheduler_batch()

    def _process_event_queue(self):
        """File event notification queue processor."""
        try:
            event = self._event_queue.get(timeout=0.05)
        except queue.Empty:
            return

        try:
            subscription, is_initial_event, files = (
                event["subscription"],
                event["is_fresh_instance"],
                event["files"],
            )
        except (KeyError, UnicodeDecodeError) as e:
            self._logger.warning("%r raised by invalid watchman event: %s", e, event)
            return

        self._logger.debug(
            "processing {} files for subscription {} (first_event={})".format(
                len(files), subscription, is_initial_event
            )
        )

        # The first watchman event for all_files is a listing of all files - ignore it.
        if (
            not is_initial_event
            and self._fs_event_service is not None
            and subscription == self._fs_event_service.PANTS_ALL_FILES_SUBSCRIPTION_NAME
        ):
            self._handle_batch_event(files)

        # However, we do want to check for the initial event in the pid file creation.
        if subscription == self._fs_event_service.PANTS_PID_SUBSCRIPTION_NAME:
            self._maybe_invalidate_scheduler_pidfile()

        if not self._watchman_is_running.is_set():
            self._watchman_is_running.set()

        self._event_queue.task_done()

    def _check_invalidation_watcher_liveness(self):
        time.sleep(self.INVALIDATION_WATCHER_LIVENESS_CHECK_INTERVAL)
        if not self._scheduler.check_invalidation_watcher_liveness():
            # Watcher failed for some reason
            self._logger.critical(
                "The graph invalidation watcher failed, so we are shutting down. Check the pantsd.log for details"
            )
            self.terminate()

    def prepare_graph(self, options: Options) -> LegacyGraphSession:
        # If any nodes exist in the product graph, wait for the initial watchman event to avoid
        # racing watchman startup vs invalidation events.
        if self._fs_event_service is not None and self._scheduler.graph_len() > 0:
            self._logger.debug(
                f"fs event service is running and graph_len > 0: waiting for initial watchman event"
            )
            self._watchman_is_running.wait()

        global_options = options.for_global_scope()
        build_id = RunTracker.global_instance().run_id
        v2_ui = global_options.get("v2_ui", False)
        zipkin_trace_v2 = options.for_scope("reporting").zipkin_trace_v2
        return self._graph_helper.new_session(zipkin_trace_v2, build_id, v2_ui)

    def graph_run_v2(
        self,
        session: LegacyGraphSession,
        specs: Specs,
        options: Options,
        options_bootstrapper: OptionsBootstrapper,
    ) -> int:
        """Perform an entire v2 run.

        The exit_code in the return indicates whether any issue was encountered.
        """

        global_options = options.for_global_scope()
        perform_loop = global_options.get("loop", False)
        v2 = global_options.v2

        if not perform_loop:
            return self._body(session, options, options_bootstrapper, specs, v2)

        # TODO: See https://github.com/pantsbuild/pants/issues/6288 regarding Ctrl+C handling.
        iterations = global_options.loop_max
        exit_code = PANTS_SUCCEEDED_EXIT_CODE

        while iterations and not self._state.is_terminating:
            try:
                exit_code = self._body(session, options, options_bootstrapper, specs, v2)
            except session.scheduler_session.execution_error_type as e:
                self._logger.warning(e)

            iterations -= 1
            while (
                iterations
                and not self._state.is_terminating
                and not self._loop_condition.wait(timeout=1)
            ):
                continue

        return exit_code

    def _body(
        self,
        session: LegacyGraphSession,
        options: Options,
        options_bootstrapper: OptionsBootstrapper,
        specs: Specs,
        v2: bool,
    ) -> int:
        exit_code = PANTS_SUCCEEDED_EXIT_CODE

        _, ambiguous_goals, v2_goals = options.goals_by_version

        if v2_goals or (ambiguous_goals and v2):
            goals = v2_goals + (ambiguous_goals if v2 else tuple())

            # N.B. @goal_rules run pre-fork in order to cache the products they request during execution.
            exit_code = session.run_goal_rules(
                options_bootstrapper=options_bootstrapper,
                union_membership=self._union_membership,
                options=options,
                goals=goals,
                specs=specs,
            )

        return exit_code

    def run(self):
        """Main service entrypoint."""
        while not self._state.is_terminating:
            if self._fs_event_service is not None:
                self._process_event_queue()
            else:
                self._check_invalidation_watcher_liveness()
            self._state.maybe_pause()


class LoopCondition:
    """A wrapped condition variable to handle deciding when loop consumers should re-run.

    Any number of threads may wait and/or notify the condition.
    """

    def __init__(self):
        super().__init__()
        self._condition = threading.Condition(threading.Lock())
        self._iteration = 0

    def notify_all(self):
        """Notifies all threads waiting for the condition."""
        with self._condition:
            self._iteration += 1
            self._condition.notify_all()

    def wait(self, timeout):
        """Waits for the condition for at most the given timeout and returns True if the condition
        triggered.

        Generally called in a loop until the condition triggers.
        """

        with self._condition:
            previous_iteration = self._iteration
            self._condition.wait(timeout)
            return previous_iteration != self._iteration
