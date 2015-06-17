# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import errno
import httplib
import json
import os
import sys
import threading
import time
import urllib
from contextlib import contextmanager
from urlparse import urlparse

from pants.base.run_info import RunInfo
from pants.base.worker_pool import SubprocPool, WorkerPool
from pants.base.workunit import WorkUnit
from pants.goal.aggregated_timings import AggregatedTimings
from pants.goal.artifact_cache_stats import ArtifactCacheStats
from pants.reporting.report import Report
from pants.subsystem.subsystem import Subsystem
from pants.util.dirutil import relative_symlink


class RunTracker(Subsystem):
  """Tracks and times the execution of a pants run.

  Also manages background work.

  Use like this:

  run_tracker.start()
  with run_tracker.new_workunit('compile'):
    with run_tracker.new_workunit('java'):
      ...
    with run_tracker.new_workunit('scala'):
      ...
  run_tracker.close()

  Can track execution against multiple 'roots', e.g., one for the main thread and another for
  background threads.
  """
  options_scope = 'run-tracker'

  # The name of the tracking root for the main thread (and the foreground worker threads).
  DEFAULT_ROOT_NAME = 'main'

  # The name of the tracking root for the background worker threads.
  BACKGROUND_ROOT_NAME = 'background'

  @classmethod
  def register_options(cls, register):
    register('--stats-upload-url', advanced=True, default=None,
             help='Upload stats to this URL on run completion.')
    register('--stats-upload-timeout', advanced=True, type=int, default=2,
             help='Wait at most this many seconds for the stats upload to complete.')
    register('--num-foreground-workers', advanced=True, type=int, default=8,
             help='Number of threads for foreground work.')
    register('--num-background-workers', advanced=True, type=int, default=8,
             help='Number of threads for background work.')

  def __init__(self, *args, **kwargs):
    super(RunTracker, self).__init__(*args, **kwargs)
    self.run_timestamp = time.time()  # A double, so we get subsecond precision for ids.
    cmd_line = ' '.join(['./pants'] + sys.argv[1:])

    # run_id is safe for use in paths.
    millis = int((self.run_timestamp * 1000) % 1000)
    run_id = 'pants_run_{}_{}'.format(
               time.strftime('%Y_%m_%d_%H_%M_%S', time.localtime(self.run_timestamp)), millis)

    info_dir = os.path.join(self.get_options().pants_workdir, self.options_scope)
    self.run_info_dir = os.path.join(info_dir, run_id)
    self.run_info = RunInfo(os.path.join(self.run_info_dir, 'info'))
    self.run_info.add_basic_info(run_id, self.run_timestamp)
    self.run_info.add_info('cmd_line', cmd_line)
    self.stats_url = self.get_options().stats_upload_url
    self.stats_timeout = self.get_options().stats_upload_timeout

    # Create a 'latest' symlink, after we add_infos, so we're guaranteed that the file exists.
    link_to_latest = os.path.join(os.path.dirname(self.run_info_dir), 'latest')

    relative_symlink(self.run_info_dir, link_to_latest)

    # Time spent in a workunit, including its children.
    self.cumulative_timings = AggregatedTimings(os.path.join(self.run_info_dir,
                                                             'cumulative_timings'))

    # Time spent in a workunit, not including its children.
    self.self_timings = AggregatedTimings(os.path.join(self.run_info_dir, 'self_timings'))

    # Hit/miss stats for the artifact cache.
    self.artifact_cache_stats = \
      ArtifactCacheStats(os.path.join(self.run_info_dir, 'artifact_cache_stats'))

    # Number of threads for foreground work.
    self._num_foreground_workers = self.get_options().num_foreground_workers

    # Number of threads for background work.
    self._num_background_workers = self.get_options().num_background_workers

    # We report to this Report.
    self.report = None

    # self._threadlocal.current_workunit contains the current workunit for the calling thread.
    # Note that multiple threads may share a name (e.g., all the threads in a pool).
    self._threadlocal = threading.local()

    # For main thread work. Created on start().
    self._main_root_workunit = None

    # For background work.  Created lazily if needed.
    self._background_worker_pool = None
    self._background_root_workunit = None

    # Trigger subproc pool init while our memory image is still clean (see SubprocPool docstring)
    SubprocPool.foreground()

    self._aborted = False

  def register_thread(self, parent_workunit):
    """Register the parent workunit for all work in the calling thread.

    Multiple threads may have the same parent (e.g., all the threads in a pool).
    """
    self._threadlocal.current_workunit = parent_workunit

  def is_under_main_root(self, workunit):
    """Is the workunit running under the main thread's root."""
    return workunit.root() == self._main_root_workunit

  def start(self, report):
    """Start tracking this pants run.

    report: an instance of pants.reporting.Report."""
    self.report = report
    self.report.open()

    self._main_root_workunit = WorkUnit(run_info_dir=self.run_info_dir, parent=None,
                                        name=RunTracker.DEFAULT_ROOT_NAME, cmd=None)
    self.register_thread(self._main_root_workunit)
    self._main_root_workunit.start()
    self.report.start_workunit(self._main_root_workunit)

  def set_root_outcome(self, outcome):
    """Useful for setup code that doesn't have a reference to a workunit."""
    self._main_root_workunit.set_outcome(outcome)

  @contextmanager
  def new_workunit(self, name, labels=None, cmd=''):
    """Creates a (hierarchical) subunit of work for the purpose of timing and reporting.

    - name: A short name for this work. E.g., 'resolve', 'compile', 'scala', 'zinc'.
    - labels: An optional iterable of labels. The reporters can use this to decide how to
              display information about this work.
    - cmd: An optional longer string representing this work.
           E.g., the cmd line of a compiler invocation.

    Use like this:

    with run_tracker.new_workunit(name='compile', labels=[WorkUnit.TASK]) as workunit:
      <do scoped work here>
      <set the outcome on workunit if necessary>

    Note that the outcome will automatically be set to failure if an exception is raised
    in a workunit, and to success otherwise, so usually you only need to set the
    outcome explicitly if you want to set it to warning.
    """
    parent = self._threadlocal.current_workunit
    with self.new_workunit_under_parent(name, parent=parent, labels=labels, cmd=cmd) as workunit:
      self._threadlocal.current_workunit = workunit
      try:
        yield workunit
      finally:
        self._threadlocal.current_workunit = parent

  @contextmanager
  def new_workunit_under_parent(self, name, parent, labels=None, cmd=''):
    """Creates a (hierarchical) subunit of work for the purpose of timing and reporting.

    - name: A short name for this work. E.g., 'resolve', 'compile', 'scala', 'zinc'.
    - parent: The new workunit is created under this parent.
    - labels: An optional iterable of labels. The reporters can use this to decide how to
              display information about this work.
    - cmd: An optional longer string representing this work.
           E.g., the cmd line of a compiler invocation.

    Task code should not typically call this directly.
    """
    workunit = WorkUnit(run_info_dir=self.run_info_dir, parent=parent, name=name, labels=labels, cmd=cmd)
    workunit.start()
    try:
      self.report.start_workunit(workunit)
      yield workunit
    except KeyboardInterrupt:
      workunit.set_outcome(WorkUnit.ABORTED)
      self._aborted = True
      raise
    except:
      workunit.set_outcome(WorkUnit.FAILURE)
      raise
    else:
      workunit.set_outcome(WorkUnit.SUCCESS)
    finally:
      self.end_workunit(workunit)

  def log(self, level, *msg_elements):
    """Log a message against the current workunit."""
    self.report.log(self._threadlocal.current_workunit, level, *msg_elements)

  def upload_stats(self):
    """Send timing results to URL specified in pants.ini"""
    def error(msg):
      # Report aleady closed, so just print error.
      print("WARNING: Failed to upload stats to {} due to {}".format(self.stats_url, msg), file=sys.stderr)

    if self.stats_url:
      params = {
        'run_info': json.dumps(self.run_info.get_as_dict()),
        'cumulative_timings': json.dumps(self.cumulative_timings.get_all()),
        'self_timings': json.dumps(self.self_timings.get_all()),
        'artifact_cache_stats': json.dumps(self.artifact_cache_stats.get_all())
        }

      headers = {"Content-type": "application/x-www-form-urlencoded", "Accept": "text/plain"}
      url = urlparse(self.stats_url)
      try:
        if url.scheme == 'https':
          http_conn = httplib.HTTPSConnection(url.netloc, timeout=self.stats_timeout)
        else:
          http_conn = httplib.HTTPConnection(url.netloc, timeout=self.stats_timeout)
        http_conn.request('POST', url.path, urllib.urlencode(params), headers)
        resp = http_conn.getresponse()
        if resp.status != 200:
          error("HTTP error code: {}".format(resp.status))
      except Exception as e:
        error("Error: {}".format(e))

  _log_levels = [Report.ERROR, Report.ERROR, Report.WARN, Report.INFO, Report.INFO]

  def end(self):
    """This pants run is over, so stop tracking it.

    Note: If end() has been called once, subsequent calls are no-ops.
    """

    if self._background_worker_pool:
      if self._aborted:
        self.log(Report.INFO, "Aborting background workers.")
        self._background_worker_pool.abort()
      else:
        self.log(Report.INFO, "Waiting for background workers to finish.")
        self._background_worker_pool.shutdown()
      self.end_workunit(self._background_root_workunit)

    SubprocPool.shutdown(self._aborted)

    # Run a dummy work unit to write out one last timestamp
    with self.new_workunit("complete"):
      pass

    self.end_workunit(self._main_root_workunit)

    outcome = self._main_root_workunit.outcome()
    if self._background_root_workunit:
      outcome = min(outcome, self._background_root_workunit.outcome())
    outcome_str = WorkUnit.outcome_string(outcome)
    log_level = RunTracker._log_levels[outcome]
    self.log(log_level, outcome_str)

    if self.run_info.get_info('outcome') is None:
      try:
        self.run_info.add_info('outcome', outcome_str)
      except IOError:
        pass  # If the goal is clean-all then the run info dir no longer exists...

    self.report.close()
    self.upload_stats()

  def end_workunit(self, workunit):
    self.report.end_workunit(workunit)
    path, duration, self_time, is_tool = workunit.end()
    self.cumulative_timings.add_timing(path, duration, is_tool)
    self.self_timings.add_timing(path, self_time, is_tool)

  def get_background_root_workunit(self):
    if self._background_root_workunit is None:
      self._background_root_workunit = WorkUnit(run_info_dir=self.run_info_dir, parent=None,
                                                name='background', cmd=None)
      self._background_root_workunit.start()
      self.report.start_workunit(self._background_root_workunit)
    return self._background_root_workunit


  def background_worker_pool(self):
    if self._background_worker_pool is None:  # Initialize lazily.
      self._background_worker_pool = WorkerPool(parent_workunit=self.get_background_root_workunit(),
                                                run_tracker=self,
                                                num_workers=self._num_background_workers)
    return self._background_worker_pool
