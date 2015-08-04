# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.pantsd.service.pants_service import PantsService
from pants.pantsd.subsystems.watchman_launcher import WatchmanLauncher


class FSEventService(PantsService):
  HANDLERS = {}

  @classmethod
  def register_handler(cls, event, handler):
    # Register callbacks for event types from other Services. -> cls.HANDLERS
    raise NotImplementedError()

  def fire_event(self, event):
    # Map an event to a set of callback handlers and fire them.
    raise NotImplementedError()

  def run(self):
    """Main service entrypoint. Called via Thread.start() via PantsDaemon.run()."""
    # Launch Watchman.
    WatchmanLauncher.global_instance().maybe_launch()

    # TODO: watchman heartbeat -> service exit (and subsequent restart to restart watchman).

    self._intentional_sleep()
