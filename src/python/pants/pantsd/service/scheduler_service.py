# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import Queue
import threading

from pants.pantsd.service.pants_service import PantsService


class SchedulerService(PantsService):
  """The pantsd scheduler service.

  This service holds an online Scheduler instance that is primed via watchman filesystem events.
  This provides for a quick fork of pants runs (via the pailgun) with a fully primed ProductGraph
  in memory.
  """

  QUEUE_SIZE = 64

  def __init__(self, fs_event_service, legacy_graph_helper):
    """
    :param FSEventService fs_event_service: An unstarted FSEventService instance for setting up
                                            filesystem event handlers.
    :param LegacyGraphHelper legacy_graph_helper: The LegacyGraphHelper instance for graph
                                                  construction.
    """
    super(SchedulerService, self).__init__()
    self._fs_event_service = fs_event_service
    self._graph_helper = legacy_graph_helper

    self._scheduler = legacy_graph_helper.scheduler
    self._logger = logging.getLogger(__name__)
    self._event_queue = Queue.Queue(maxsize=self.QUEUE_SIZE)
    self._watchman_is_running = threading.Event()

  @property
  def change_calculator(self):
    """Surfaces the change calculator."""
    return self._graph_helper.change_calculator

  def setup(self, lifecycle_lock, fork_lock):
    """Service setup."""
    super(SchedulerService, self).setup(lifecycle_lock, fork_lock)
    # Register filesystem event handlers on an FSEventService instance.
    self._fs_event_service.register_all_files_handler(self._enqueue_fs_event)

  def _enqueue_fs_event(self, event):
    """Watchman filesystem event handler for BUILD/requirements.txt updates. Called via a thread."""
    self._logger.info('enqueuing {} changes for subscription {}'
                      .format(len(event['files']), event['subscription']))
    self._event_queue.put(event)

  def _handle_batch_event(self, files):
    self._logger.debug('handling change event for: %s', files)
    with self.fork_lock:
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
                                               [f.decode('utf-8') for f in event['files']])
    except (KeyError, UnicodeDecodeError) as e:
      self._logger.warn('%r raised by invalid watchman event: %s', e, event)
      return

    self._logger.debug('processing {} files for subscription {} (first_event={})'
                       .format(len(files), subscription, is_initial_event))

    # The first watchman event is a listing of all files - ignore it.
    if not is_initial_event:
      self._handle_batch_event(files)

    if not self._watchman_is_running.is_set():
      self._watchman_is_running.set()

    self._event_queue.task_done()

  def product_graph_len(self):
    """Provides the size of the captive product graph.

    :returns: The node count for the captive product graph.
    """
    return self._scheduler.graph_len()

  def warm_product_graph(self, spec_roots):
    """Runs an execution request against the captive scheduler given a set of input specs to warm.

    :returns: A `LegacyGraphHelper` instance for graph construction.
    """
    # If any nodes exist in the product graph, wait for the initial watchman event to avoid
    # racing watchman startup vs invalidation events.
    graph_len = self._scheduler.graph_len()
    if graph_len > 0:
      self._logger.debug('graph len was {}, waiting for initial watchman event'.format(graph_len))
      self._watchman_is_running.wait()

    with self.fork_lock:
      self._graph_helper.warm_product_graph(spec_roots)
      return self._graph_helper

  def run(self):
    """Main service entrypoint."""
    while not self.is_killed:
      self._process_event_queue()
