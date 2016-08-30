# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import os
import traceback

from concurrent.futures import ThreadPoolExecutor

from pants.pantsd.service.pants_service import PantsService
from pants.pantsd.watchman import Watchman


class FSEventService(PantsService):
  """Filesystem Event Service.

  This is the primary service coupling to watchman and is responsible for subscribing to and
  reading events from watchman's UNIX socket and firing callbacks in pantsd. Callbacks are
  executed in a configurable threadpool but are generally expected to be short-lived.
  """

  ZERO_DEPTH = ['depth', 'eq', 0]

  def __init__(self, watchman, build_root, worker_count):
    """
    :param Watchman watchman: The Watchman instance as provided by the WatchmanLauncher subsystem.
    :param str build_root: The current build root.
    :param int worker_count: The total number of workers to use for the internally managed
                             ThreadPoolExecutor.
    """
    super(FSEventService, self).__init__()
    self._logger = logging.getLogger(__name__)
    self._watchman = watchman
    self._build_root = os.path.realpath(build_root)
    self._worker_count = worker_count
    self._executor = None
    self._handlers = {}

  def setup(self, executor=None):
    self._executor = executor or ThreadPoolExecutor(max_workers=self._worker_count)

  def terminate(self):
    """An extension of PantsService.terminate() that shuts down the executor if so configured."""
    if self._executor:
      self._logger.info('shutting down threadpool')
      self._executor.shutdown()
    super(FSEventService, self).terminate()

  def register_all_files_handler(self, callback, name='all_files'):
    """Registers a subscription for all files under a given watch path.

    :param func callback: the callback to execute on each filesystem event
    :param str name:      the subscription name as used by watchman
    """
    self.register_handler(
      name,
      dict(
        fields=['name'],
        # Request events for all file types.
        # NB: Touching a file invalidates its parent directory due to:
        #   https://github.com/facebook/watchman/issues/305
        # ...but if we were to skip watching directories, we'd still have to invalidate
        # the parents of any changed files, and we wouldn't see creation/deletion of
        # empty directories.
        expression=[
          'allof',  # All of the below rules must be true to match.
          ['not', ['dirname', 'dist', self.ZERO_DEPTH]],  # Exclude the ./dist dir.
          # N.B. 'wholename' ensures we match against the absolute ('x/y/z') vs base path ('z').
          ['not', ['pcre', r'^\..*', 'wholename']],  # Exclude files in hidden dirs (.pants.d etc).
          ['not', ['match', '*.pyc']]  # Exclude .pyc files.
          # TODO(kwlzn): Make exclusions here optionable.
          # Related: https://github.com/pantsbuild/pants/issues/2956
        ]
      ),
      callback
    )

  def register_handler(self, name, metadata, callback):
    """Register subscriptions and their event handlers.

    :param str name:      the subscription name as used by watchman
    :param dict metadata: a dictionary of metadata to be serialized and passed to the watchman
                          subscribe command. this should include the match expression as well
                          as any required callback fields.
    :param func callback: the callback to execute on each matching filesystem event
    """
    assert name not in self._handlers, 'duplicate handler name: {}'.format(name)
    assert (
      isinstance(metadata, dict) and 'fields' in metadata and 'expression' in metadata
    ), 'invalid handler metadata!'
    self._handlers[name] = Watchman.EventHandler(name=name, metadata=metadata, callback=callback)

  def fire_callback(self, handler_name, event_data):
    """Fire an event callback for a given handler."""
    return self._handlers[handler_name].callback(event_data)

  def run(self):
    """Main service entrypoint. Called via Thread.start() via PantsDaemon.run()."""

    if not (self._watchman and self._watchman.is_alive()):
      raise self.ServiceError('watchman is not running, bailing!')

    # Enable watchman for the build root.
    self._watchman.watch_project(self._build_root)

    futures = {}
    id_counter = 0
    subscriptions = self._handlers.values()

    # Setup subscriptions and begin the main event firing loop.
    for handler_name, event_data in self._watchman.subscribed(self._build_root, subscriptions):
      # On death, break from the loop and contextmgr to terminate callback threads.
      if self.is_killed: break

      if event_data:
        # As we receive events from watchman, submit them asynchronously to the executor.
        future = self._executor.submit(self.fire_callback, handler_name, event_data)
        futures[future] = handler_name

      # Process and log results for completed futures.
      for completed_future in [_future for _future in futures if _future.done()]:
        handler_name = futures.pop(completed_future)
        id_counter += 1

        try:
          result = completed_future.result()
        except Exception:
          result = traceback.format_exc()

        if result is not None:
          # Truthy results or those that raise exceptions are treated as failures.
          self._logger.warning('callback ID {} for {} failed: {}'
                               .format(id_counter, handler_name, result))
        else:
          self._logger.debug('callback ID {} for {} succeeded'.format(id_counter, handler_name))
