# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import os
import threading

from pants.engine.internals.scheduler import Scheduler
from pants.pantsd.service.pants_service import PantsService
from pants.pantsd.watchman import Watchman


class FSEventService(PantsService):
    """Filesystem Event Service.

    This is the primary service coupling to watchman and is responsible for subscribing to and
    reading events from watchman's UNIX socket and firing callbacks in pantsd. Callbacks are
    executed in a configurable threadpool but are generally expected to be short-lived.
    """

    ZERO_DEPTH = ["depth", "eq", 0]

    PANTS_ALL_FILES_SUBSCRIPTION_NAME = "all_files"

    def __init__(
        self, watchman: Watchman, scheduler: Scheduler, build_root: str,
    ):
        """
        :param watchman: The Watchman instance as provided by the WatchmanLauncher subsystem.
        :param session: A SchedulerSession to invalidate for.
        :param build_root: The current build root.
        """
        super().__init__()
        self._logger = logging.getLogger(__name__)
        self._watchman = watchman
        self._build_root = os.path.realpath(build_root)
        self._watchman_is_running = threading.Event()
        self._scheduler_session = scheduler.new_session(
            zipkin_trace_v2=False, build_id="fs_event_service_session"
        )

        self._handler = Watchman.EventHandler(
            name=self.PANTS_ALL_FILES_SUBSCRIPTION_NAME,
            metadata=dict(
                fields=["name"],
                # Request events for all file types.
                # NB: Touching a file invalidates its parent directory due to:
                #   https://github.com/facebook/watchman/issues/305
                # ...but if we were to skip watching directories, we'd still have to invalidate
                # the parents of any changed files, and we wouldn't see creation/deletion of
                # empty directories.
                expression=[
                    "allof",  # All of the below rules must be true to match.
                    ["not", ["dirname", "dist", self.ZERO_DEPTH]],  # Exclude the ./dist dir.
                    # N.B. 'wholename' ensures we match against the absolute ('x/y/z') vs base path ('z').
                    [
                        "not",
                        ["pcre", r"^\..*", "wholename"],
                    ],  # Exclude files in hidden dirs (.pants.d etc).
                    ["not", ["match", "*.pyc"]]  # Exclude .pyc files.
                    # TODO(kwlzn): Make exclusions here optionable.
                    # Related: https://github.com/pantsbuild/pants/issues/2956
                ],
            ),
            # NB: We stream events from Watchman in `self.run`, so we don't need a callback.
            callback=lambda: None,
        )

    def await_started(self):
        return self._watchman_is_running.wait()

    def _handle_all_files_event(self, event):
        """File event notification queue processor."""
        try:
            is_initial_event, files = (
                event["is_fresh_instance"],
                event["files"],
            )
        except (KeyError, UnicodeDecodeError) as e:
            self._logger.warning("%r raised by invalid watchman event: %s", e, event)
            return

        # The first watchman event for all_files is a listing of all files - ignore it.
        if is_initial_event:
            self._logger.debug(f"watchman now watching {len(files)} files")
        else:
            self._logger.debug(f"handling change event for: {len(files)}")
            self._scheduler_session.invalidate_files(files)

    def run(self):
        """Main service entrypoint.

        Called via Thread.start() via PantsDaemon.run().
        """

        if not (self._watchman and self._watchman.is_alive()):
            raise PantsService.ServiceError("watchman is not running, bailing!")

        # Enable watchman for the build root and register our all_files handler.
        self._watchman.watch_project(self._build_root)

        # Setup subscriptions and begin the main event firing loop.
        for _, event_data in self._watchman.subscribed(self._build_root, [self._handler]):
            self._state.maybe_pause()
            if self._state.is_terminating:
                break
            if not event_data:
                continue

            self._handle_all_files_event(event_data)
            if not self._watchman_is_running.is_set():
                self._watchman_is_running.set()
