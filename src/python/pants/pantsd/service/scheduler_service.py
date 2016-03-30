# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import itertools
import logging
import os
import Queue

import six

from pants.pantsd.service.pants_service import PantsService


class SchedulerService(PantsService):
  """The pantsd scheduler service.

  This service holds an online Scheduler instance that is primed via watchman filesystem events.
  This provides for a quick fork of pants runs (via the pailgun) with a fully primed ProductGraph
  in memory.
  """

  def __init__(self, scheduler, fs_event_service, subject_classes, fs_node_type):
    """
    :param LocalScheduler scheduler: A Scheduler instance.
    :param FSEventService fs_event_service: An unstarted FSEventService instance for setting up
                                            filesystem event handlers.
    :param seq subject_classes: A sequence containing classes to match as subjects for invalidation.
    :param class fs_node_type: The class representing filesystem nodes.
    """
    super(SchedulerService, self).__init__()
    self._logger = logging.getLogger(__name__)

    self._event_queue = Queue.Queue(maxsize=64)
    self._scheduler = scheduler
    self._fs_event_service = fs_event_service
    self._subject_classes = subject_classes
    self._fs_node_type = fs_node_type

  def __len__(self):
    return len(self._scheduler.product_graph.completed_nodes())

  def setup(self):
    """Registers filesystem event handlers on an FSEventService instance."""
    self._fs_event_service.register_all_files_handler(self._enqueue_fs_event)

  def _enqueue_fs_event(self, event):
    """Watchman filesystem event handler for BUILD/requirements.txt updates. Called via a thread."""
    self._logger.info('enqueuing {} changes for subscription {}'
                      .format(len(event['files']), event['subscription']))
    self._event_queue.put(event)

  def _handle_batch_event(self, files):
    if not self._scheduler:
      self._logger.debug('no scheduler. ignoring event.')
      return

    self._logger.debug('handling change event for: %s', files)
    self._invalidate_graph_by_files(files)

  def _generate_subjects(self, filenames):
    """Given filenames, generate a set of subject keys for invalidation predicate matching."""
    # Here we include a dirname of every file in the generation path to also invalidate parent
    # dir DirectoryListing nodes. Watchman can do this natively by matching against ['type', 'd'] -
    # however it's very aggressive (a simple `vim dir/file` will result in an invalidation event
    # against `dir` even if `file` isn't modified). This relaxes things to invalidate only on actual
    # file change and also affords for build_root directory invalidation, which isn't possible via
    # Watchman without setting the watch-project root to one level higher than the build_root.
    file_paths = itertools.chain(filenames, (os.path.dirname(f) for f in filenames))
    for file_path in file_paths:
      for subject_class in self._subject_classes:
        subject = subject_class(six.text_type(file_path))
        self._logger.debug('generated invalidation subject: %s', subject)
        yield subject

  def _invalidate_graph_by_files(self, filenames):
    """Map filesystem events to graph invalidations."""
    subjects = set(self._generate_subjects(filenames))
    def predicate(node):
      return type(node) is self._fs_node_type and node.subject in subjects
    invalid_count = self._scheduler.invalidate(predicate)
    self._logger.info('invalidated {} nodes'.format(invalid_count))

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

  def run(self):
    """Main service entrypoint."""
    while not self.is_killed:
      self._process_event_queue()
