# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import functools
import itertools
import math
import os
import shutil
import threading
from abc import ABCMeta, abstractmethod
from typing import Any, List

from pants.backend.jvm.tasks.nailgun_task import NailgunTask
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.option.custom_types import dir_option
from pants.process.xargs import Xargs
from pants.util.dirutil import fast_relpath, safe_mkdir_for_all
from pants.util.memo import memoized_property


class RewriteBase(NailgunTask, metaclass=ABCMeta):
  """Abstract base class for JVM-based tools that check/rewrite sources."""

  @classmethod
  def register_options(cls, register):
    super().register_options(register)
    register('--target-types',
             default=cls.target_types(),
             advanced=True, type=list,
             help='The target types to apply formatting to.')
    if cls.sideeffecting:
      register('--output-dir', advanced=True, type=dir_option, fingerprint=True,
               help='Path to output directory. Any updated files will be written here. '
               'If not specified, files will be modified in-place.')

    register('--files-per-worker', type=int, fingerprint=False,
             default=None,
             help='Number of files to use per each scalafmt execution.')
    register('--worker-count', type=int, fingerprint=False,
             default=None,
             help='Total number of parallel scalafmt threads or processes to run.')

  @classmethod
  def target_types(cls):
    """Returns a list of target type names (e.g.: `scala_library`) this rewriter operates on."""
    raise NotImplementedError()

  @classmethod
  def source_extension(cls):
    """Returns the source extension this rewriter operates on (e.g.: `.scala`)"""
    raise NotImplementedError()

  @memoized_property
  def _formatted_target_types(self):
    aliases = set(self.get_options().target_types)
    registered_aliases = self.context.build_configuration.registered_aliases()
    return tuple({target_type
                  for alias in aliases
                  for target_type in registered_aliases.target_types_by_alias[alias]})

  @property
  def cache_target_dirs(self):
    return not self.sideeffecting

  def execute(self):
    """Runs the tool on all source files that are located."""
    relevant_targets = self._get_non_synthetic_targets(self.get_targets())

    if self.sideeffecting:
      # Always execute sideeffecting tasks without invalidation.
      self._execute_for(relevant_targets)
    else:
      # If the task is not sideeffecting we can use invalidation.
      with self.invalidated(relevant_targets) as invalidation_check:
        self._execute_for([vt.target for vt in invalidation_check.invalid_vts])

  def _split_by_threads(self, inputs_list_of_lists: List[List[Any]], invoke_fn):
    parent_workunit = self.context.run_tracker.get_current_workunit()

    # Propagate exceptions in threads to the toplevel by checking this variable after joining all
    # the threads.
    all_exceptions = []

    def thread_exception_wrapper(fn):
      @functools.wraps(fn)
      def inner(*args, **kwargs):
        try:
          fn(*args, **kwargs)
        except Exception as e:
          all_exceptions.append(e)
      return inner

    all_threads = [
      threading.Thread(
        name=f'scalafmt invocation thread #{idx}/{len(inputs_list_of_lists)}',
        target=thread_exception_wrapper(invoke_fn),
        args=[parent_workunit, inputs_single_list],
      )
      for idx, inputs_single_list in enumerate(inputs_list_of_lists)
    ]
    for thread in all_threads:
      thread.start()
    for thread in all_threads:
      try:
        thread.join()
      except Exception as e:
        raise TaskError(str(e)) from e
    if all_exceptions:
      joined_str = ', '.join(str(e) for e in all_exceptions)
      raise TaskError(f'all errors: {joined_str}') from all_exceptions[0]

  def _execute_for(self, targets):
    target_sources = self._calculate_sources(targets)
    if not target_sources:
      return

    if self.get_options().files_per_worker is not None:
      # If --files-per-worker is specified, split the target sources and run in separate threads!
      n = self.get_options().files_per_worker
      inputs_list_of_lists = [
        target_sources[i:i + n]
        for i in range(0, len(target_sources), n)
      ]
      self._split_by_threads(inputs_list_of_lists=inputs_list_of_lists, invoke_fn=self._invoke_tool)
    elif self.get_options().worker_count is not None:
      # If --worker-count is specified, split the target sources into that many
      # threads, and run in separate threads!
      num_processes = self.get_options().worker_count
      sources_iterator = iter(target_sources)
      inputs_list_of_lists = [
        list(itertools.islice(sources_iterator, 0, math.ceil(len(target_sources) / num_processes)))
        for _ in range(0, num_processes)
      ]
      self._split_by_threads(inputs_list_of_lists=inputs_list_of_lists, invoke_fn=self._invoke_tool)
    else:
      # Otherwise, pass in the parent workunit to Xargs, which is passed into self._invoke_tool.
      parent_workunit = self.context.run_tracker.get_current_workunit()
      result = Xargs(self._invoke_tool, constant_args=[parent_workunit]).execute(target_sources)
      if result != 0:
        raise TaskError('{} is improperly implemented: a failed process '
                        'should raise an exception earlier.'.format(type(self).__name__))

  def _invoke_tool(self, parent_workunit, target_sources):
    # We want to avoid executing anything if there are no sources to generate.
    if not target_sources:
      return 0
    self.context.run_tracker.register_thread(parent_workunit)
    buildroot = get_buildroot()
    toolroot = buildroot
    if self.sideeffecting and self.get_options().output_dir:
      toolroot = self.get_options().output_dir
      new_sources = [
        (target, os.path.join(toolroot, fast_relpath(source, buildroot)))
        for target, source in target_sources
      ]
      old_file_paths = [source for _, source in target_sources]
      new_file_paths = [source for _, source in new_sources]
      safe_mkdir_for_all(new_file_paths)
      for old, new in zip(old_file_paths, new_file_paths):
        shutil.copyfile(old, new)
      target_sources = new_sources
    result = self.invoke_tool(parent_workunit, toolroot, target_sources)
    self.process_result(result)
    return result

  @abstractmethod
  def invoke_tool(self, absolute_root, target_sources):
    """Invoke the tool on the given (target, absolute source) tuples.

    Sources are guaranteed to be located below the given root.

    Returns the UNIX return code of the tool.
    """

  @property
  @abstractmethod
  def sideeffecting(self):
    """True if this command has sideeffects: ie, mutates the working copy."""

  @abstractmethod
  def process_result(self, return_code):
    """Given a return code, process the result of the tool.

    No return value is expected. If an error occurred while running the tool, raising a TaskError
    with a useful error message is required.
    """

  def _get_non_synthetic_targets(self, targets):
    return [target for target in targets
            if isinstance(target, self._formatted_target_types)
            and target.has_sources(self.source_extension())
            and not target.is_synthetic]

  def _calculate_sources(self, targets):
    return [(target, os.path.join(get_buildroot(), source))
            for target in targets
            for source in target.sources_relative_to_buildroot()
            if source.endswith(self.source_extension())]
