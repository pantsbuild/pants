from contextlib import contextmanager
import httplib
import json
import os
import sys
import threading
import time
import urllib
from urlparse import urlparse

from twitter.pants.base.config import Config
from twitter.pants.base.run_info import RunInfo
from twitter.pants.base.worker_pool import WorkerPool
from twitter.pants.base.workunit import WorkUnit
from twitter.pants.reporting.report import Report

from .aggregated_timings import AggregatedTimings
from .artifact_cache_stats import ArtifactCacheStats


class RunTracker(object):
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

  # The name of the tracking root for the main thread (and the foreground worker threads).
  DEFAULT_ROOT_NAME = 'main'

  # The name of the tracking root for the background worker threads.
  BACKGROUND_ROOT_NAME = 'background'

  @classmethod
  def from_config(cls, config):
    if not isinstance(config, Config):
      raise ValueError('Expected a Config object, given %s of type %s' % (config, type(config)))
    info_dir = RunInfo.dir(config)
    stats_upload_url = config.getdefault('stats_upload_url', default=None)
    num_foreground_workers = config.getdefault('num_foreground_workers', default=8)
    num_background_workers = config.getdefault('num_background_workers', default=8)
    return cls(info_dir,
               stats_upload_url=stats_upload_url,
               num_foreground_workers=num_foreground_workers,
               num_background_workers=num_background_workers)

  def __init__(self,
               info_dir,
               stats_upload_url=None,
               num_foreground_workers=8,
               num_background_workers=8):
    self.run_timestamp = time.time()  # A double, so we get subsecond precision for ids.
    cmd_line = ' '.join(['./pants'] + sys.argv[1:])

    # run_id is safe for use in paths.
    millis = (self.run_timestamp * 1000) % 1000
    run_id = 'pants_run_%s_%d' % \
             (time.strftime('%Y_%m_%d_%H_%M_%S', time.localtime(self.run_timestamp)), millis)

    self.info_dir = os.path.join(info_dir, run_id)
    self.run_info = RunInfo(os.path.join(self.info_dir, 'info'))
    self.run_info.add_basic_info(run_id, self.run_timestamp)
    self.run_info.add_info('cmd_line', cmd_line)
    self.stats_url = stats_upload_url

    # Create a 'latest' symlink, after we add_infos, so we're guaranteed that the file exists.
    link_to_latest = os.path.join(os.path.dirname(self.info_dir), 'latest')
    if os.path.exists(link_to_latest):
      os.unlink(link_to_latest)
    os.symlink(self.info_dir, link_to_latest)

    # Time spent in a workunit, including its children.
    self.cumulative_timings = AggregatedTimings(os.path.join(self.info_dir, 'cumulative_timings'))

    # Time spent in a workunit, not including its children.
    self.self_timings = AggregatedTimings(os.path.join(self.info_dir, 'self_timings'))

    # Hit/miss stats for the artifact cache.
    self.artifact_cache_stats = \
      ArtifactCacheStats(os.path.join(self.info_dir, 'artifact_cache_stats'))

    # Number of threads for foreground work.
    self._num_foreground_workers = num_foreground_workers

    # Number of threads for background work.
    self._num_background_workers = num_background_workers

    # We report to this Report.
    self.report = None

    # self._threadlocal.current_workunit contains the current workunit for the calling thread.
    # Note that multiple threads may share a name (e.g., all the threads in a pool).
    self._threadlocal = threading.local()

    # For main thread work. Created on start().
    self._main_root_workunit = None

    # For concurrent foreground work.  Created lazily if needed.
    # Associated with the main thread's root workunit.
    self._foreground_worker_pool = None

    # For background work.  Created lazily if needed.
    self._background_worker_pool = None
    self._background_root_workunit = None

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

    self._main_root_workunit = WorkUnit(run_tracker=self, parent=None, labels=[],
                                        name=RunTracker.DEFAULT_ROOT_NAME, cmd=None)
    self.register_thread(self._main_root_workunit)
    self._main_root_workunit.start()
    self.report.start_workunit(self._main_root_workunit)

  @contextmanager
  def new_workunit(self, name, labels=None, cmd=''):
    """Creates a (hierarchical) subunit of work for the purpose of timing and reporting.

    - name: A short name for this work. E.g., 'resolve', 'compile', 'scala', 'zinc'.
    - labels: An optional iterable of labels. The reporters can use this to decide how to
              display information about this work.
    - cmd: An optional longer string representing this work.
           E.g., the cmd line of a compiler invocation.

    Use like this:

    with run_tracker.new_workunit(name='compile', labels=[WorkUnit.GOAL]) as workunit:
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
    workunit = WorkUnit(run_tracker=self, parent=parent, name=name, labels=labels, cmd=cmd)
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
      self.report.end_workunit(workunit)
      workunit.end()

  def log(self, level, *msg_elements):
    """Log a message against the current workunit."""
    self.report.log(self._threadlocal.current_workunit, level, *msg_elements)

  def upload_stats(self):
    """Send timing results to URL specified in pants.ini"""
    def error(msg):
      # Report aleady closed, so just print error.
      print("WARNING: Failed to upload stats. %s" % msg)

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
          http_conn = httplib.HTTPSConnection(url.netloc)
        else:
          http_conn = httplib.HTTPConnection(url.netloc)
        http_conn.request('POST', url.path, urllib.urlencode(params), headers)
        resp = http_conn.getresponse()
        if resp.status != 200:
          error("HTTP error code: %d" % resp.status)
      except Exception as e:
        error("Error: %s" % e)

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
      self.report.end_workunit(self._background_root_workunit)
      self._background_root_workunit.end()

    if self._foreground_worker_pool:
      if self._aborted:
        self.log(Report.INFO, "Aborting foreground workers.")
        self._foreground_worker_pool.abort()
      else:
        self.log(Report.INFO, "Waiting for foreground workers to finish.")
        self._foreground_worker_pool.shutdown()

    self.report.end_workunit(self._main_root_workunit)
    self._main_root_workunit.end()

    outcome = self._main_root_workunit.outcome()
    if self._background_root_workunit:
      outcome = min(outcome, self._background_root_workunit.outcome())
    outcome_str = WorkUnit.outcome_string(outcome)
    log_level = WorkUnit.choose_for_outcome(outcome, Report.ERROR, Report.ERROR,
                                            Report.WARN, Report.INFO, Report.INFO)
    self.log(log_level, outcome_str)

    if self.run_info.get_info('outcome') is None:
      try:
        self.run_info.add_info('outcome', outcome_str)
      except IOError:
        pass  # If the goal is clean-all then the run info dir no longer exists...

    self.report.close()
    self.upload_stats()

  def foreground_worker_pool(self):
    if self._foreground_worker_pool is None:  # Initialize lazily.
      self._foreground_worker_pool = WorkerPool(parent_workunit=self._main_root_workunit,
                                                run_tracker=self,
                                                num_workers=self._num_foreground_workers)
    return self._foreground_worker_pool

  def get_background_root_workunit(self):
    if self._background_root_workunit is None:
      self._background_root_workunit = WorkUnit(run_tracker=self, parent=None, labels=[],
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
