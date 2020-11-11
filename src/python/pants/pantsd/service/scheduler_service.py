# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import time
from typing import Optional, Tuple, cast

import psutil

from pants.engine.fs import PathGlobs, Snapshot
from pants.engine.internals.scheduler import ExecutionTimeoutError
from pants.init.engine_initializer import GraphScheduler
from pants.pantsd.service.pants_service import PantsService


class SchedulerService(PantsService):
    """The pantsd scheduler service.

    This service uses the scheduler to watch the filesystem and determine whether pantsd needs to
    restart in order to reload its state.
    """

    # The interval on which we will long-poll the invalidation globs. If a glob changes, the poll
    # will return immediately, so this value primarily affects how frequently the `run` method
    # will check the terminated condition.
    INVALIDATION_POLL_INTERVAL = 0.5
    # A grace period after startup that we will wait before enforcing our pid.
    PIDFILE_GRACE_PERIOD = 5

    def __init__(
        self,
        *,
        graph_scheduler: GraphScheduler,
        build_root: str,
        invalidation_globs: Tuple[str, ...],
        pidfile: str,
        pid: int,
        max_memory_usage_in_bytes: int,
    ) -> None:
        """
        :param graph_scheduler: The GraphScheduler instance for graph construction.
        :param build_root: The current build root.
        :param invalidation_globs: A tuple of `globs` that when encountered in filesystem event
                                   subscriptions will tear down the daemon.
        :param pidfile: A pidfile which should contain this processes' pid in order for the daemon
                        to remain valid.
        :param pid: This processes' pid.
        :param max_memory_usage_in_bytes: The maximum memory usage of the process: the service will
                                          shut down if it observes more than this amount in use.
        """
        super().__init__()
        self._graph_helper = graph_scheduler
        self._build_root = build_root

        self._scheduler = graph_scheduler.scheduler
        # This session is only used for checking whether any invalidation globs have been invalidated.
        # It is not involved with a build itself; just with deciding when we should restart pantsd.
        self._scheduler_session = self._scheduler.new_session(
            build_id="scheduler_service_session",
        )
        self._logger = logging.getLogger(__name__)

        # NB: We declare these as a single field so that they can be changed atomically.
        self._invalidation_globs_and_snapshot: Tuple[Tuple[str, ...], Optional[Snapshot]] = (
            invalidation_globs,
            None,
        )

        self._pidfile = pidfile
        self._pid = pid
        self._max_memory_usage_in_bytes = max_memory_usage_in_bytes

    def _get_snapshot(self, globs: Tuple[str, ...], poll: bool) -> Optional[Snapshot]:
        """Returns a Snapshot of the input globs.

        If poll=True, will wait for up to INVALIDATION_POLL_INTERVAL for the globs to have changed,
        and will return None if they have not changed.
        """
        timeout = self.INVALIDATION_POLL_INTERVAL if poll else None
        try:
            snapshot = self._scheduler_session.product_request(
                Snapshot,
                subjects=[PathGlobs(globs)],
                poll=poll,
                timeout=timeout,
            )[0]
            return cast(Snapshot, snapshot)
        except ExecutionTimeoutError:
            if poll:
                return None
            raise

    def _check_invalidation_globs(self, poll: bool):
        """Check the digest of our invalidation Snapshot and exit if it has changed."""
        globs, invalidation_snapshot = self._invalidation_globs_and_snapshot
        assert invalidation_snapshot is not None, "Should have been eagerly initialized in run."

        snapshot = self._get_snapshot(globs, poll=poll)
        if snapshot is None or snapshot.digest == invalidation_snapshot.digest:
            return

        before = set(invalidation_snapshot.files + invalidation_snapshot.dirs)
        after = set(snapshot.files + snapshot.dirs)
        added = after - before
        removed = before - after
        if added or removed:
            description = f"+{added or '{}'}, -{removed or '{}'}"
        else:
            description = f"content changed ({snapshot.digest} fs {invalidation_snapshot.digest})"
        self._logger.critical(
            f"saw filesystem changes covered by invalidation globs: {description}. terminating the daemon."
        )
        self.terminate()

    def _check_pidfile(self):
        try:
            with open(self._pidfile, "r") as f:
                pid_from_file = f.read()
        except IOError:
            raise Exception(f"Could not read pants pidfile at {self._pidfile}.")
        if int(pid_from_file) != self._pid:
            raise Exception(f"Another instance of pantsd is running at {pid_from_file}")

    def _check_memory_usage(self):
        memory_usage_in_bytes = psutil.Process(self._pid).memory_info()[0]
        if memory_usage_in_bytes > self._max_memory_usage_in_bytes:
            raise Exception(
                f"pantsd process {self._pid} was using "
                f"{memory_usage_in_bytes} bytes of memory (above the limit of "
                f"{self._max_memory_usage_in_bytes} bytes)."
            )

    def _check_invalidation_watcher_liveness(self):
        self._scheduler.check_invalidation_watcher_liveness()

    def run(self):
        """Main service entrypoint."""
        # N.B. We compute the invalidating fileset eagerly at launch with an assumption that files
        # that exist at startup are the only ones that can affect the running daemon.
        globs, _ = self._invalidation_globs_and_snapshot
        self._invalidation_globs_and_snapshot = (globs, self._get_snapshot(globs, poll=False))
        self._logger.debug("watching invalidation patterns: {}".format(globs))
        pidfile_deadline = time.time() + self.PIDFILE_GRACE_PERIOD

        while not self._state.is_terminating:
            try:
                self._state.maybe_pause()
                self._check_invalidation_watcher_liveness()
                self._check_memory_usage()
                if time.time() > pidfile_deadline:
                    self._check_pidfile()
                # NB: This is a long poll that will keep us from looping too quickly here.
                self._check_invalidation_globs(poll=True)
            except Exception as e:
                # Watcher failed for some reason
                self._logger.critical(f"The scheduler was invalidated: {e!r}")
                self.terminate()
