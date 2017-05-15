# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import ast
import json
import multiprocessing
import os
import sys
import threading
import time
import uuid
from contextlib import contextmanager

import requests

from pants.base.build_environment import get_pants_cachedir
from pants.base.run_info import RunInfo
from pants.base.worker_pool import SubprocPool, WorkerPool
from pants.base.workunit import WorkUnit
from pants.goal.aggregated_timings import AggregatedTimings
from pants.goal.artifact_cache_stats import ArtifactCacheStats
from pants.reporting.report import Report
from pants.stats.statsdb import StatsDBFactory
from pants.subsystem.subsystem import Subsystem
from pants.util.dirutil import relative_symlink, safe_file_dump


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

  :API: public
  """
  options_scope = 'run-tracker'

  # The name of the tracking root for the main thread (and the foreground worker threads).
  DEFAULT_ROOT_NAME = 'main'

  # The name of the tracking root for the background worker threads.
  BACKGROUND_ROOT_NAME = 'background'

  @classmethod
  def subsystem_dependencies(cls):
    return (StatsDBFactory,)

  @classmethod
  def register_options(cls, register):
    register('--stats-upload-url', advanced=True, default=None,
             help='Upload stats to this URL on run completion.')
    register('--stats-upload-timeout', advanced=True, type=int, default=2,
             help='Wait at most this many seconds for the stats upload to complete.')
    register('--num-foreground-workers', advanced=True, type=int,
             default=multiprocessing.cpu_count(),
             help='Number of threads for foreground work.')
    register('--num-background-workers', advanced=True, type=int,
             default=multiprocessing.cpu_count(),
             help='Number of threads for background work.')
    register('--stats-local-json-file', advanced=True, default=None,
             help='Write stats to this local json file on run completion.')

  def __init__(self, *args, **kwargs):
    """
    :API: public
    """
    super(RunTracker, self).__init__(*args, **kwargs)
    run_timestamp = time.time()
    cmd_line = ' '.join(['pants'] + sys.argv[1:])

    # run_id is safe for use in paths.
    millis = int((run_timestamp * 1000) % 1000)
    run_id = 'pants_run_{}_{}_{}'.format(
      time.strftime('%Y_%m_%d_%H_%M_%S', time.localtime(run_timestamp)), millis,
      uuid.uuid4().hex)

    info_dir = os.path.join(self.get_options().pants_workdir, self.options_scope)
    self.run_info_dir = os.path.join(info_dir, run_id)
    self.run_info = RunInfo(os.path.join(self.run_info_dir, 'info'))
    self.run_info.add_basic_info(run_id, run_timestamp)
    self.run_info.add_info('cmd_line', cmd_line)

    # Create a 'latest' symlink, after we add_infos, so we're guaranteed that the file exists.
    link_to_latest = os.path.join(os.path.dirname(self.run_info_dir), 'latest')

    relative_symlink(self.run_info_dir, link_to_latest)

    # A lock to ensure that adding to stats at the end of a workunit
    # operates thread-safely.
    self._stats_lock = threading.Lock()

    # Time spent in a workunit, including its children.
    self.cumulative_timings = AggregatedTimings(os.path.join(self.run_info_dir,
                                                             'cumulative_timings'))

    # Time spent in a workunit, not including its children.
    self.self_timings = AggregatedTimings(os.path.join(self.run_info_dir, 'self_timings'))

    # Hit/miss stats for the artifact cache.
    self.artifact_cache_stats = \
      ArtifactCacheStats(os.path.join(self.run_info_dir, 'artifact_cache_stats'))

    # Log of success/failure/aborted for each workunit.
    self.outcomes = {}

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

    # Trigger subproc pool init while our memory image is still clean (see SubprocPool docstring).
    SubprocPool.set_num_processes(self._num_foreground_workers)
    SubprocPool.foreground()

    self._aborted = False

    # Data will be organized first by target and then scope.
    # Eg:
    # {
    #   'target/address:name': {
    #     'running_scope': {
    #       'run_duration': 356.09
    #     },
    #     'GLOBAL': {
    #       'target_type': 'pants.test'
    #     }
    #   }
    # }
    self._target_to_data = {}

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

    report: an instance of pants.reporting.Report.
    """
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
  def new_workunit(self, name, labels=None, cmd='', log_config=None):
    """Creates a (hierarchical) subunit of work for the purpose of timing and reporting.

    - name: A short name for this work. E.g., 'resolve', 'compile', 'scala', 'zinc'.
    - labels: An optional iterable of labels. The reporters can use this to decide how to
              display information about this work.
    - cmd: An optional longer string representing this work.
           E.g., the cmd line of a compiler invocation.
    - log_config: An optional tuple WorkUnit.LogConfig of task-level options affecting reporting.

    Use like this:

    with run_tracker.new_workunit(name='compile', labels=[WorkUnitLabel.TASK]) as workunit:
      <do scoped work here>
      <set the outcome on workunit if necessary>

    Note that the outcome will automatically be set to failure if an exception is raised
    in a workunit, and to success otherwise, so usually you only need to set the
    outcome explicitly if you want to set it to warning.

    :API: public
    """
    parent = self._threadlocal.current_workunit
    with self.new_workunit_under_parent(name, parent=parent, labels=labels, cmd=cmd,
                                        log_config=log_config) as workunit:
      self._threadlocal.current_workunit = workunit
      try:
        yield workunit
      finally:
        self._threadlocal.current_workunit = parent

  @contextmanager
  def new_workunit_under_parent(self, name, parent, labels=None, cmd='', log_config=None):
    """Creates a (hierarchical) subunit of work for the purpose of timing and reporting.

    - name: A short name for this work. E.g., 'resolve', 'compile', 'scala', 'zinc'.
    - parent: The new workunit is created under this parent.
    - labels: An optional iterable of labels. The reporters can use this to decide how to
              display information about this work.
    - cmd: An optional longer string representing this work.
           E.g., the cmd line of a compiler invocation.

    Task code should not typically call this directly.

    :API: public
    """
    workunit = WorkUnit(run_info_dir=self.run_info_dir, parent=parent, name=name, labels=labels,
                        cmd=cmd, log_config=log_config)
    workunit.start()

    outcome = WorkUnit.FAILURE  # Default to failure we will override if we get success/abort.
    try:
      self.report.start_workunit(workunit)
      yield workunit
    except KeyboardInterrupt:
      outcome = WorkUnit.ABORTED
      self._aborted = True
      raise
    else:
      outcome = WorkUnit.SUCCESS
    finally:
      workunit.set_outcome(outcome)
      self.end_workunit(workunit)

  def log(self, level, *msg_elements):
    """Log a message against the current workunit."""
    self.report.log(self._threadlocal.current_workunit, level, *msg_elements)

  @classmethod
  def post_stats(cls, url, stats, timeout=2):
    """POST stats to the given url.

    :return: True if upload was successful, False otherwise.
    """
    def error(msg):
      # Report aleady closed, so just print error.
      print('WARNING: Failed to upload stats to {} due to {}'.format(url, msg),
            file=sys.stderr)
      return False

    # TODO(benjy): The upload protocol currently requires separate top-level params, with JSON
    # values.  Probably better for there to be one top-level JSON value, namely json.dumps(stats).
    # But this will first require changing the upload receiver at every shop that uses this
    # (probably only Foursquare at present).
    params = {k: json.dumps(v) for (k, v) in stats.items()}
    try:
      r = requests.post(url, data=params, timeout=timeout)
      if r.status_code != requests.codes.ok:
        return error("HTTP error code: {}".format(r.status_code))
    except Exception as e:  # Broad catch - we don't want to fail the build over upload errors.
      return error("Error: {}".format(e))
    return True

  @classmethod
  def write_stats_to_json(cls, file_name, stats):
    """Write stats to a local json file.

    :return: True if successfully written, False otherwise.
    """
    params = json.dumps(stats)
    try:
      with open(file_name, 'w') as f:
        f.write(params)
    except Exception as e:  # Broad catch - we don't want to fail in stats related failure.
      print('WARNING: Failed to write stats to {} due to Error: {}'.format(file_name, e),
            file=sys.stderr)
      return False
    return True

  def store_stats(self):
    """Store stats about this run in local and optionally remote stats dbs."""
    run_information = self.run_info.get_as_dict()
    target_data = run_information.get('target_data', None)
    if target_data:
      run_information['target_data'] = ast.literal_eval(target_data)

    stats = {
      'run_info': run_information,
      'cumulative_timings': self.cumulative_timings.get_all(),
      'self_timings': self.self_timings.get_all(),
      'artifact_cache_stats': self.artifact_cache_stats.get_all(),
      'outcomes': self.outcomes
    }
    # Dump individual stat file.
    # TODO(benjy): Do we really need these, once the statsdb is mature?
    stats_file = os.path.join(get_pants_cachedir(), 'stats',
                              '{}.json'.format(self.run_info.get_info('id')))
    safe_file_dump(stats_file, json.dumps(stats))

    # Add to local stats db.
    StatsDBFactory.global_instance().get_db().insert_stats(stats)

    # Upload to remote stats db.
    stats_url = self.get_options().stats_upload_url
    if stats_url:
      pid = os.fork()
      if pid == 0:
        try:
          self.post_stats(stats_url, stats, timeout=self.get_options().stats_upload_timeout)
        finally:
          os._exit(0)

    # Write stats to local json file.
    stats_json_file_name = self.get_options().stats_local_json_file
    if stats_json_file_name:
      self.write_stats_to_json(stats_json_file_name, stats)

  _log_levels = [Report.ERROR, Report.ERROR, Report.WARN, Report.INFO, Report.INFO]

  def end(self):
    """This pants run is over, so stop tracking it.

    Note: If end() has been called once, subsequent calls are no-ops.

    :return: 0 for success, 1 for failure.
    """
    if self._background_worker_pool:
      if self._aborted:
        self.log(Report.INFO, "Aborting background workers.")
        self._background_worker_pool.abort()
      else:
        self.log(Report.INFO, "Waiting for background workers to finish.")
        self._background_worker_pool.shutdown()
      self.end_workunit(self._background_root_workunit)

    self.shutdown_worker_pool()

    # Run a dummy work unit to write out one last timestamp.
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
      # If the goal is clean-all then the run info dir no longer exists, so ignore that error.
      self.run_info.add_info('outcome', outcome_str, ignore_errors=True)

    if self._target_to_data:
      self.run_info.add_info('target_data', self._target_to_data)

    self.report.close()
    self.store_stats()

    return 1 if outcome in [WorkUnit.FAILURE, WorkUnit.ABORTED] else 0

  def end_workunit(self, workunit):
    self.report.end_workunit(workunit)
    path, duration, self_time, is_tool = workunit.end()

    # These three operations may not be thread-safe, and workunits may run in separate threads
    # and thus end concurrently, so we want to lock these operations.
    with self._stats_lock:
      self.cumulative_timings.add_timing(path, duration, is_tool)
      self.self_timings.add_timing(path, self_time, is_tool)
      self.outcomes[path] = workunit.outcome_string(workunit.outcome())

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

  def shutdown_worker_pool(self):
    """Shuts down the SubprocPool.

    N.B. This exists only for internal use and to afford for fork()-safe operation in pantsd.
    """
    SubprocPool.shutdown(self._aborted)

  @staticmethod
  def create_dict_with_nested_keys_and_val(all_keys, value, index):
    """ Recursively constructs a nested dictionary with the keys pointing to the value.

    :param list of string all_keys: A list of keys to be nested as a dictionary.
    :param dict or string value: The value of the information being stored.
    :param int index: The index of the last element of the list of keys.
    :return: dict of nested keys leading to the value.
    """
    if index > 0:
      new_val = {all_keys[index]: value}
      return RunTracker.create_dict_with_nested_keys_and_val(all_keys, new_val, index - 1)
    elif index == 0:
      return {all_keys[index]: value}


  @staticmethod
  def merge_list_of_keys_into_dict(data, keys, value, index):
    """ Recursively merge list of keys that points to the given value into data.

    :param dict data: Dictionary to be updated.
    :param list of string keys: The keys that point to where the value should be stored.
           Will recursively find the correct place to store in the nested dicts.
    :param primitive value: The value of the information being stored.
    :param int index: The index into the list of keys (starting form the beginning). This should
           always be 0 when being called outside of this function.
    """
    if len(keys) == 0:
      raise ValueError('Keys must contain at least one key')
    if len(keys) < 2 or not data:
      new_data_to_add = RunTracker.create_dict_with_nested_keys_and_val(keys, value, len(keys) - 1)
      data.update(new_data_to_add)
      return
    else:
      this_keys_contents = data.get(keys[index])
      if this_keys_contents:
        if isinstance(this_keys_contents, dict):
          new_keys = keys[index+1:]
          RunTracker.merge_list_of_keys_into_dict(this_keys_contents, new_keys, value, 0)
        else:
          new_keys = keys[index+1:]
          new_data_to_add = RunTracker.create_dict_with_nested_keys_and_val(new_keys, value, len(new_keys) - 1)
          data[keys[index]] = new_data_to_add
          return
      else:
        new_keys = keys[index:]
        new_data_to_add = RunTracker.create_dict_with_nested_keys_and_val(new_keys, value, len(new_keys) - 1)
        data.update(new_data_to_add)
        return

  def report_target_info(self, scope, target, keys, val):
    """Add target information to run_info under target_data.

    Will Recursively construct a nested dict with the keys provided.

    :param string scope: The scope for which we are reporting the information.
    :param string target: The target for which we want to store information.
    :param list of string keys: The keys that will be recursively
           nested and pointing to the information being stored.
    :param primitive val: The value of the information being stored.

    :API: public
    """
    new_key_list = [target, scope]
    new_key_list += keys
    RunTracker.merge_list_of_keys_into_dict(self._target_to_data, new_key_list, val, 0)
