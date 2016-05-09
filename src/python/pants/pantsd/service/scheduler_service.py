# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import Queue

from pants.pantsd.service.pants_service import PantsService


class SchedulerService(PantsService):
  """The pantsd scheduler service.

  This service holds an online Scheduler instance that is primed via watchman filesystem events.
  This provides for a quick fork of pants runs (via the pailgun) with a fully primed ProductGraph
  in memory.
  """

  def __init__(self, fs_event_service, legacy_graph_helper):
    """
    :param FSEventService fs_event_service: An unstarted FSEventService instance for setting up
                                            filesystem event handlers.
    :param LegacyGraphHelper legacy_graph_helper: The LegacyGraphHelper instance for graph
                                                  construction.
    """
    super(SchedulerService, self).__init__()
    self._fs_event_service = fs_event_service
    self._scheduler = legacy_graph_helper.scheduler
    self._engine = legacy_graph_helper.engine
    self._symbol_table_cls = legacy_graph_helper.symbol_table_cls
    self._build_graph_facade_cls = legacy_graph_helper.legacy_graph_cls

    self._logger = logging.getLogger(__name__)
    self._event_queue = Queue.Queue(maxsize=64)

  def setup(self):
    """Service setup."""
    # Register filesystem event handlers on an FSEventService instance.
    self._fs_event_service.register_all_files_handler(self._enqueue_fs_event)

    # Start the engine.
    self._engine.start()

  def _enqueue_fs_event(self, event):
    """Watchman filesystem event handler for BUILD/requirements.txt updates. Called via a thread."""
    self._logger.info('enqueuing {} changes for subscription {}'
                      .format(len(event['files']), event['subscription']))
    self._event_queue.put(event)

  def _handle_batch_event(self, files):
    self._logger.debug('handling change event for: %s', files)
    if not self._scheduler:
      self._logger.debug('no scheduler. ignoring event.')
      return

    self._scheduler.invalidate_files(files)

  def _process_event_queue(self):
    """File event notification queue processor."""
    try:
      event = self._event_queue.get(timeout=1)
    except Queue.Empty:
      return

    try:
      subscription, is_initial_event, files = (event['subscription'],
                                               event['is_fresh_instance'],
                                               event['files'])
    except KeyError:
      self._logger.warn('invalid watchman event: %s', event)
      return

    self._logger.debug('processing {} files for subscription {} (first_event={})'
                       .format(len(files), subscription, is_initial_event))

    if not is_initial_event:  # Ignore the initial all files event from watchman.
      self._handle_batch_event(files)
    self._event_queue.task_done()

  def get_build_graph(self, spec_roots):
    """Returns a factory that provides a legacy BuildGraph given a set of input specs."""
    graph = self._build_graph_facade_cls(self._scheduler, self._engine, self._symbol_table_cls)
    with self._scheduler.locked():
      for _ in graph.inject_specs_closure(spec_roots):  # Ensure the entire generator is unrolled.
        pass
    self._logger.debug('engine cache stats: %s', self._engine._cache.get_stats())
    self._logger.debug('build_graph is: %s', graph)
    return graph

  def run(self):
    """Main service entrypoint."""
    while not self.is_killed:
      self._process_event_queue()

  def terminate(self):
    """An extension of PantsService.terminate() that tears down the engine."""
    self._engine.close()
    super(SchedulerService, self).terminate()
