# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
from typing import List, Optional, Tuple, cast

import psutil

from pants.engine.fs import PathGlobs, Snapshot
from pants.engine.internals.scheduler import ExecutionTimeoutError
from pants.init.engine_initializer import LegacyGraphScheduler
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

    def __init__(
        self,
        *,
        legacy_graph_scheduler: LegacyGraphScheduler,
        build_root: str,
        invalidation_globs: List[str],
        max_memory_usage_pid: int,
        max_memory_usage_in_bytes: int,
    ) -> None:
        """
        :param legacy_graph_scheduler: The LegacyGraphScheduler instance for graph construction.
        :param build_root: The current build root.
        :param invalidation_globs: A list of `globs` that when encountered in filesystem event
                                   subscriptions will tear down the daemon.
        :param max_memory_usage_pid: A pid to monitor the memory usage of (generally our own!).
        :param max_memory_usage_in_bytes: The maximum memory usage of the process: the service will
                                          shut down if it observes more than this amount in use.
        """
        super().__init__()
        self._graph_helper = legacy_graph_scheduler
        self._build_root = build_root

        self._scheduler = legacy_graph_scheduler.scheduler
        # This session is only used for checking whether any invalidation globs have been invalidated.
        # It is not involved with a build itself; just with deciding when we should restart pantsd.
        self._scheduler_session = self._scheduler.new_session(build_id="scheduler_service_session",)
        self._logger = logging.getLogger(__name__)

        # NB: We declare these as a single field so that they can be changed atomically.
        self._invalidation_globs_and_snapshot: Tuple[Tuple[str, ...], Optional[Snapshot]] = (
            tuple(invalidation_globs),
            None,
        )

        self._max_memory_usage_pid = max_memory_usage_pid
        self._max_memory_usage_in_bytes = max_memory_usage_in_bytes

    def _get_snapshot(self, globs: Tuple[str, ...], poll: bool) -> Optional[Snapshot]:
        """Returns a Snapshot of the input globs.

        If poll=True, will wait for up to INVALIDATION_POLL_INTERVAL for the globs to have changed,
        and will return None if they have not changed.
        """
        timeout = self.INVALIDATION_POLL_INTERVAL if poll else None
        try:
            snapshot = self._scheduler_session.product_request(
                Snapshot, subjects=[PathGlobs(globs)], poll=poll, timeout=timeout,
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

    def _check_memory_usage(self):
        try:
            memory_usage_in_bytes = psutil.Process(self._max_memory_usage_pid).memory_info()[0]
            if memory_usage_in_bytes > self._max_memory_usage_in_bytes:
                raise Exception(
                    f"pantsd process {self._max_memory_usage_pid} was using "
                    f"{memory_usage_in_bytes} bytes of memory (above the limit of "
                    f"{self._max_memory_usage_in_bytes} bytes)."
                )
        except Exception as e:
            # Watcher failed for some reason
            self._logger.critical(f"The scheduler was invalidated: {e!r}")
            self.terminate()

    def _check_invalidation_watcher_liveness(self):
        try:
            self._scheduler.check_invalidation_watcher_liveness()
        except Exception as e:
            # Watcher failed for some reason
            self._logger.critical(f"The scheduler was invalidated: {e!r}")
            self.terminate()

    def run(self):
        """Main service entrypoint."""
        # N.B. We compute the invalidating fileset eagerly at launch with an assumption that files
        # that exist at startup are the only ones that can affect the running daemon.
        globs, _ = self._invalidation_globs_and_snapshot
        self._invalidation_globs_and_snapshot = (globs, self._get_snapshot(globs, poll=False))
        self._logger.debug("watching invalidation patterns: {}".format(globs))

        while not self._state.is_terminating:
            self._state.maybe_pause()
            self._check_invalidation_watcher_liveness()
            self._check_memory_usage()
            # NB: This is a long poll that will keep us from looping too quickly here.
            self._check_invalidation_globs(poll=True)
