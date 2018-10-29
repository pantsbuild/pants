# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import logging
import os
import queue
import sys
import threading
from builtins import open

from twitter.common.dirutil import Fileset

from pants.init.target_roots_calculator import TargetRootsCalculator
from pants.pantsd.service.pants_service import PantsService


class SchedulerService(PantsService):
  """The pantsd scheduler service.

  This service holds an online Scheduler instance that is primed via watchman filesystem events.
  This provides for a quick fork of pants runs (via the pailgun) with a fully primed ProductGraph
  in memory.
  """

  QUEUE_SIZE = 64

  def __init__(
    self,
    fs_event_service,
    legacy_graph_scheduler,
    build_root,
    invalidation_globs,
    pantsd_pidfile,
  ):
    """
    :param FSEventService fs_event_service: An unstarted FSEventService instance for setting up
                                            filesystem event handlers.
    :param LegacyGraphScheduler legacy_graph_scheduler: The LegacyGraphScheduler instance for graph
                                                        construction.
    :param str build_root: The current build root.
    :param list invalidation_globs: A list of `globs` that when encountered in filesystem event
                                    subscriptions will tear down the daemon.
    :param string pantsd_pidfile: The path to the pantsd pidfile for fs event monitoring.
    """
    super(SchedulerService, self).__init__()
    self._fs_event_service = fs_event_service
    self._graph_helper = legacy_graph_scheduler
    self._invalidation_globs = invalidation_globs
    self._build_root = build_root
    self._pantsd_pidfile = pantsd_pidfile

    self._scheduler = legacy_graph_scheduler.scheduler
    self._logger = logging.getLogger(__name__)
    self._event_queue = queue.Queue(maxsize=self.QUEUE_SIZE)
    self._watchman_is_running = threading.Event()
    self._invalidating_files = set()

    self._loop_condition = LoopCondition()

  @staticmethod
  def _combined_invalidating_fileset_from_globs(glob_strs, root):
    return set.union(*(Fileset.globs(glob_str, root=root)() for glob_str in glob_strs))

  def setup(self, services):
    """Service setup."""
    super(SchedulerService, self).setup(services)
    # Register filesystem event handlers on an FSEventService instance.
    self._fs_event_service.register_all_files_handler(self._enqueue_fs_event)

    # N.B. We compute this combined set eagerly at launch with an assumption that files
    # that exist at startup are the only ones that can affect the running daemon.
    if self._invalidation_globs:
      self._invalidating_files = self._combined_invalidating_fileset_from_globs(
        self._invalidation_globs,
        self._build_root
      )
    self._logger.info('watching invalidating files: {}'.format(self._invalidating_files))

    if self._pantsd_pidfile:
      self._fs_event_service.register_pidfile_handler(self._pantsd_pidfile, self._enqueue_fs_event)

  def _enqueue_fs_event(self, event):
    """Watchman filesystem event handler for BUILD/requirements.txt updates. Called via a thread."""
    self._logger.info('enqueuing {} changes for subscription {}'
                      .format(len(event['files']), event['subscription']))
    self._event_queue.put(event)

  def _maybe_invalidate_scheduler_batch(self, files):
    invalidating_files = self._invalidating_files
    if any(f in invalidating_files for f in files):
      self._logger.fatal('saw file events covered by invalidation globs, terminating the daemon.')
      self.terminate()

  def _maybe_invalidate_scheduler_pidfile(self):
    new_pid = self._check_pid_changed()
    if new_pid is not False:
      self._logger.fatal('{} says pantsd PID is {} but my PID is: {}: terminating'.format(
        self._pantsd_pidfile,
        new_pid,
        os.getpid(),
      ))
      self.terminate()

  def _check_pid_changed(self):
    """Reads pidfile and returns False if its PID is ours, else a printable (maybe falsey) value."""
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
    self._logger.debug('handling change event for: %s', files)

    self._maybe_invalidate_scheduler_batch(files)

    invalidated = self._scheduler.invalidate_files(files)
    if invalidated:
      self._loop_condition.notify_all()

  def _process_event_queue(self):
    """File event notification queue processor."""
    try:
      event = self._event_queue.get(timeout=0.05)
    except queue.Empty:
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
      if subscription == self._fs_event_service.PANTS_PID_SUBSCRIPTION_NAME:
        self._maybe_invalidate_scheduler_pidfile()
      else:
        self._handle_batch_event(files)

    if not self._watchman_is_running.is_set():
      self._watchman_is_running.set()

    self._event_queue.task_done()

  def product_graph_len(self):
    """Provides the size of the captive product graph.

    :returns: The node count for the captive product graph.
    """
    return self._scheduler.graph_len()

  def prefork(self, options, build_config):
    """Runs all pre-fork logic in the process context of the daemon.

    :returns: `(LegacyGraphSession, TargetRoots)`
    """
    # If any nodes exist in the product graph, wait for the initial watchman event to avoid
    # racing watchman startup vs invalidation events.
    graph_len = self._scheduler.graph_len()
    if graph_len > 0:
      self._logger.debug('graph len was {}, waiting for initial watchman event'.format(graph_len))
      self._watchman_is_running.wait()

    session = self._graph_helper.new_session()
    if options.for_global_scope().loop:
      return session, self._prefork_loop(session, options)
    else:
      return session, self._prefork_body(session, options)

  def _prefork_loop(self, session, options):
    # TODO: See https://github.com/pantsbuild/pants/issues/6288 regarding Ctrl+C handling.
    iterations = options.for_global_scope().loop_max
    target_roots = None
    while iterations and not self._state.is_terminating:
      try:
        target_roots = self._prefork_body(session, options)
      except session.scheduler_session.execution_error_type as e:
        # Render retryable exceptions raised by the Scheduler.
        print(e, file=sys.stderr)

      iterations -= 1
      while iterations and not self._state.is_terminating and not self._loop_condition.wait(timeout=1):
        continue
    return target_roots

  def _prefork_body(self, session, options):
    global_options = options.for_global_scope()
    target_roots = TargetRootsCalculator.create(
      options=options,
      session=session.scheduler_session,
      symbol_table=session.symbol_table,
      exclude_patterns=tuple(global_options.exclude_target_regexp) if global_options.exclude_target_regexp else tuple(),
      tags=tuple(global_options.tag) if global_options.tag else tuple()
    )

    if global_options.v1:
      session.warm_product_graph(target_roots)

    if global_options.v2:
      if not global_options.v1:
        session.validate_goals(options.goals)

      # N.B. @console_rules run pre-fork in order to cache the products they request during execution.
      session.run_console_rules(options.goals, target_roots)

    return target_roots

  def run(self):
    """Main service entrypoint."""
    while not self._state.is_terminating:
      self._process_event_queue()
      self._state.maybe_pause()


class LoopCondition(object):
  """A wrapped condition variable to handle deciding when loop consumers should re-run.

  Any number of threads may wait and/or notify the condition.
  """

  def __init__(self):
    super(LoopCondition, self).__init__()
    self._condition = threading.Condition(threading.Lock())
    self._iteration = 0

  def notify_all(self):
    """Notifies all threads waiting for the condition."""
    with self._condition:
      self._iteration += 1
      self._condition.notify_all()

  def wait(self, timeout):
    """Waits for the condition for at most the given timeout and returns True if the condition triggered.

    Generally called in a loop until the condition triggers.
    """

    with self._condition:
      previous_iteration = self._iteration
      self._condition.wait(timeout)
      return previous_iteration != self._iteration
