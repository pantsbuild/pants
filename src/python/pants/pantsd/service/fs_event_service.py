# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import os

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
    PANTS_PID_SUBSCRIPTION_NAME = "pantsd_pid"

    def __init__(self, watchman, build_root):
        """
        :param Watchman watchman: The Watchman instance as provided by the WatchmanLauncher subsystem.
        :param str build_root: The current build root.
        """
        super().__init__()
        self._logger = logging.getLogger(__name__)
        self._watchman = watchman
        self._build_root = os.path.realpath(build_root)
        self._handlers = {}

    def register_all_files_handler(self, callback, name):
        """Registers a subscription for all files under a given watch path.

        :param func callback: the callback to execute on each filesystem event
        :param str name:      the subscription name as used by watchman
        """
        self.register_handler(
            name,
            dict(
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
            callback,
        )

    def register_pidfile_handler(self, pidfile_path, callback):
        """

        :param pidfile_path: Path to the pidfile, relative to the build root
        :param callback:
        :return:
        """
        self.register_handler(
            self.PANTS_PID_SUBSCRIPTION_NAME,
            dict(
                fields=["name"],
                expression=[
                    "allof",
                    ["dirname", os.path.dirname(pidfile_path)],
                    ["name", os.path.basename(pidfile_path)],
                ],
            ),
            callback,
        )

    def register_handler(self, name, metadata, callback):
        """Register subscriptions and their event handlers.

        :param str name:      the subscription name as used by watchman
        :param dict metadata: a dictionary of metadata to be serialized and passed to the watchman
                              subscribe command. this should include the match expression as well
                              as any required callback fields.
        :param func callback: the callback to execute on each matching filesystem event
        """
        assert name not in self._handlers, "duplicate handler name: {}".format(name)
        assert (
            isinstance(metadata, dict) and "fields" in metadata and "expression" in metadata
        ), "invalid handler metadata!"
        self._handlers[name] = Watchman.EventHandler(
            name=name, metadata=metadata, callback=callback
        )

    def fire_callback(self, handler_name, event_data):
        """Fire an event callback for a given handler."""
        return self._handlers[handler_name].callback(event_data)

    def run(self):
        """Main service entrypoint.

        Called via Thread.start() via PantsDaemon.run().
        """

        if not (self._watchman and self._watchman.is_alive()):
            raise PantsService.ServiceError("watchman is not running, bailing!")

        # Enable watchman for the build root.
        self._watchman.watch_project(self._build_root)

        subscriptions = list(self._handlers.values())

        # Setup subscriptions and begin the main event firing loop.
        for handler_name, event_data in self._watchman.subscribed(self._build_root, subscriptions):
            self._state.maybe_pause()
            if self._state.is_terminating:
                break

            if event_data:
                # As we receive events from watchman, trigger the relevant handlers.
                self.fire_callback(handler_name, event_data)
