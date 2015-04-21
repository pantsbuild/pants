# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import Queue as queue
from collections import OrderedDict, defaultdict, namedtuple

from pants.backend.jvm.tasks.jvm_compile.jvm_compile_strategy import JvmCompileStrategy
from pants.backend.jvm.tasks.jvm_compile.resource_mapping import ResourceMapping
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.base.worker_pool import Work, WorkerPool
from pants.util.dirutil import safe_mkdir, safe_walk


UNSTARTED = 'Unstarted'
SUCCESS = 'Success'
FAILURE = 'Failure'
QUEUED = 'Queued'

class ExecutionGraph(object):

  class ExecutionFailure(Exception):
    """Raised when tasks fail during execution"""

  class Work(namedtuple('ExecutionWork', ['fn', 'dependencies', 'on_success', 'on_failure'])):
    def __call__(self, *args, **kwargs):
      self.fn()

    def run_success_callback(self):
      if self.on_success:
        self.on_success()

    def run_failure_callback(self):
      if self.on_failure:
        self.on_failure()

  class StatusTable(object):
    DONE_STATES = {SUCCESS, FAILURE}

    def __init__(self, keys):
      self._statuses = {key: UNSTARTED for key in keys}

    def mark_as(self, state, key):
      self._statuses[key] = state

    def all_done(self):
      return all(s in self.DONE_STATES for s in self._statuses.values())

    def unfinished_work(self):
      """Returns a dict of name to current status, only including work that's not done"""
      return {key: stat for key, stat in self._statuses.items() if stat not in self.DONE_STATES}

    def get(self, key):
      return self._statuses.get(key)

    def has_failures(self):
      return any(stat == FAILURE for stat in self._statuses.values())

    def all_successful(self, keys):
      return all(stat == SUCCESS for stat in [self._statuses[k] for k in keys])

  def __init__(self, parent_work_unit, run_tracker, worker_count, log):
    self._log = log
    self._parent_work_unit = parent_work_unit
    self._run_tracker = run_tracker
    self._worker_count = worker_count
    self._dependees = defaultdict(list)
    self._work = {}
    self._work_keys_as_scheduled = []

  def log_dot_graph(self):
    for key in self._work_keys_as_scheduled:
      self._log.debug("{} -> {{\n  {}\n}}".format(key, ',\n  '.join(self._dependees[key])))

  def schedule(self, key, fn, dependency_keys, on_success=None, on_failure=None):
    """Inserts work into the execution graph with its dependencies.

    Assumes dependencies have already been scheduled, and raises an error otherwise."""
    self._work_keys_as_scheduled.append(key)
    self._work[key] = self.Work(fn, dependency_keys, on_success, on_failure)
    for dep_name in dependency_keys:
      if dep_name not in self._work:
        raise Exception("Expected {} not scheduled before dependent {}".format(dep_name, key))
      self._dependees[dep_name].append(key)

  def find_work_without_dependencies(self):
    # Topo sort doesn't mean all no-dependency targets are listed first,
    # so we look for all work without dependencies
    return filter(
      lambda key: len(self._work[key].dependencies) == 0, self._work_keys_as_scheduled)

  def execute(self):
    """Runs scheduled work, ensuring all dependencies for each element are done before execution.

    spawns a work pool of the specified size.
    submits all the work without any dependencies
    when a unit of work finishes,
      if it is successful
        calls success callback
        checks for dependees whose dependencies are all successful, and submits them
      if it fails
        calls failure callback
        marks dependees as failed and queues them directly into the finished work queue
    when all work is either successful or failed,
      cleans up the work pool
    if there's an exception on the main thread,
      calls failure callback for unfinished work
      aborts work pool
      re-raises
    """
    self.log_dot_graph()

    status_table = self.StatusTable(self._work_keys_as_scheduled)
    finished_queue = queue.Queue()

    work_without_dependencies = self.find_work_without_dependencies()
    if len(work_without_dependencies) == 0:
      raise self.ExecutionFailure("No work without dependencies! There must be a "
                                  "circular dependency")

    def worker(work_key, work):
      try:
        work()
        result = (work_key, True, None)
      except Exception as e:
        result = (work_key, False, e)
      finished_queue.put(result)

    pool = WorkerPool(self._parent_work_unit, self._run_tracker, self._worker_count)

    def submit_work(work_keys):
      for work_key in work_keys:
        status_table.mark_as(QUEUED, work_key)
        pool.submit_async_work(Work(worker, [(work_key, (self._work[work_key]))]))

    try:
      submit_work(work_without_dependencies)

      while not status_table.all_done():
        try:
          finished_key, success, value = finished_queue.get(timeout=10)
        except queue.Empty:
          self._log.debug("Waiting on \n  {}".format(
            "\n  ".join(
              "{}: {}".format(key, state) for key, state in status_table.unfinished_work().items()
            )))
          continue

        direct_dependees = self._dependees[finished_key]
        finished_work = self._work[finished_key]
        if success:
          status_table.mark_as(SUCCESS, finished_key)
          finished_work.run_success_callback()

          ready_dependees = [dependee for dependee in direct_dependees
                             if status_table.all_successful(finished_work.dependencies)]

          submit_work(ready_dependees)
        else:
          status_table.mark_as(FAILURE, finished_key)
          finished_work.run_failure_callback()

          # propagate failures downstream
          for dependee in direct_dependees:
            finished_queue.put((dependee, False, None))

        self._log.debug("{} finished with status {}".format(finished_key,
                                                            status_table.get(finished_key)))

      pool.shutdown()
      if status_table.has_failures():
        raise self.ExecutionFailure("Compile failed")
    except Exception as e:
      pool.abort()
      # Call failure callbacks for work that's unfinished.
      for key in status_table.unfinished_work().keys():
        self._work[key].run_failure_callback()

      raise self.ExecutionFailure("Error running work: {}".format(e.message), e)

class JvmCompileIsolatedStrategy(JvmCompileStrategy):
  """A strategy for JVM compilation that uses per-target classpaths and analysis."""

  @classmethod
  def register_options(cls, register, language):
    register('--worker-count', type=int, default=1,
             help='The number of worker threads to use to compile {lang} sources'
             .format(lang=language))

  def __init__(self, context, options, workdir, analysis_tools, sources_predicate):
    super(JvmCompileIsolatedStrategy, self).__init__(context, options, workdir, analysis_tools,
                                                     sources_predicate)

    # Various working directories.
    self._analysis_dir = os.path.join(workdir, 'isolated-analysis')
    self._classes_dir = os.path.join(workdir, 'isolated-classes')
    self._options = options

  def name(self):
    return 'isolated'

  def compile_context(self, target):
    analysis_file = JvmCompileStrategy._analysis_for_target(self._analysis_dir, target)
    classes_dir = os.path.join(self._classes_dir, target.id)
    return self.CompileContext(target,
                               analysis_file,
                               classes_dir,
                               self._sources_for_target(target))

  def pre_compile(self):
    super(JvmCompileIsolatedStrategy, self).pre_compile()
    safe_mkdir(self._analysis_dir)
    safe_mkdir(self._classes_dir)

  def prepare_compile(self, cache_manager, all_targets, relevant_targets):
    super(JvmCompileIsolatedStrategy, self).prepare_compile(cache_manager, all_targets,
                                                            relevant_targets)

    # Update the classpath by adding relevant target's classes directories to its classpath.
    compile_classpaths = self.context.products.get_data('compile_classpath')
    self.context.log.info([t.address.spec for t in relevant_targets])
    for target in relevant_targets:
      cc = self.compile_context(target)
      compile_classpaths.add_for_target(target, [(conf, cc.classes_dir) for conf in self._confs])
      self.validate_analysis(cc.analysis_file)

  def invalidation_hints(self, relevant_targets):
    # No partitioning.
    return (0, None)

  def _upstream_analysis(self, compile_contexts, target):
    """Returns tuples of classes_dir->analysis_file for the closure of the target."""
    # If we have a compile context for the target, include it.
    for dep in target.closure():
      if dep in compile_contexts:
        compile_context = compile_contexts[dep]
        yield compile_context.classes_dir, compile_context.analysis_file

  def compute_classes_by_source(self, compile_contexts):
    buildroot = get_buildroot()
    classes_by_src_by_context = defaultdict(dict)
    for compile_context in compile_contexts:
      if not os.path.exists(compile_context.analysis_file):
        continue
      products = self._analysis_parser.parse_products_from_path(compile_context.analysis_file,
                                                                compile_context.classes_dir)
      classes_by_src = classes_by_src_by_context[compile_context]
      for src, classes in products.items():
        relsrc = os.path.relpath(src, buildroot)
        classes_by_src[relsrc] = classes
    return classes_by_src_by_context

  def _create_compile_contexts_for_targets(self, relevant_targets):
    compile_contexts = OrderedDict()
    for target in relevant_targets:
      compile_context = self.compile_context(target)
      safe_mkdir(compile_context.classes_dir)
      compile_contexts[target] = compile_context

    return compile_contexts

  # Compute any extra compile-time-only classpath elements.
  # TODO(benjy): Model compile-time vs. runtime classpaths more explicitly.
  # TODO(benjy): Add a pre-execute goal for injecting deps into targets, so e.g.,
  # we can inject a dep on the scala runtime library and still have it ivy-resolve.
  def _compute_extra_classpath(self, extra_compile_time_classpath_elements):
    def extra_compile_classpath_iter():
      for conf in self._confs:
        for jar in extra_compile_time_classpath_elements:
          yield (conf, jar)

    return list(extra_compile_classpath_iter())

  def _compute_classpath_entries(self, compile_classpaths, compile_context,
                                 extra_compile_time_classpath):
    # Generate a classpath specific to this compile and target, and include analysis
    # for upstream targets.
    raw_compile_classpath = compile_classpaths.get_for_target(compile_context.target)
    compile_classpath = extra_compile_time_classpath + list(raw_compile_classpath)
    # Validate that the classpath is located within the working copy, which simplifies
    # relativizing the analysis files.
    self._validate_classpath(compile_classpath)
    # Filter the final classpath and gather upstream analysis.
    return [entry for conf, entry in compile_classpath if conf in self._confs]

  def exec_graph_key_for_target(self, compile_target):
    return "compile-{}".format(compile_target.address.spec)

  def compile_chunk(self,
                    invalidation_check,
                    all_targets,
                    relevant_targets,
                    invalid_targets,
                    extra_compile_time_classpath_elements,
                    compile_vts,
                    register_vts,
                    update_artifact_cache_vts_work):
    """Executes compilations for the invalid targets contained in a single chunk."""
    assert invalid_targets, "compile_chunk should only be invoked if there are invalid targets."
    with self.context.new_workunit('isolated') as workunit:
      exec_graph = ExecutionGraph(workunit,
                                  self.context.run_tracker,
                                  self._options.worker_count,
                                  self.context.log)

    # Get the classpath generated by upstream JVM tasks and our own prepare_compile().
    compile_classpaths = self.context.products.get_data('compile_classpath')

    extra_compile_time_classpath = self._compute_extra_classpath(
      extra_compile_time_classpath_elements)

    compile_contexts = self._create_compile_contexts_for_targets(relevant_targets)

    # Now compile each invalid target one by one.
    invalid_vts_count = len(invalidation_check.invalid_vts_partitioned)
    for idx, vts in enumerate(invalidation_check.invalid_vts_partitioned):
      assert len(vts.targets) == 1, ("Requested one target per partition, got {}".format(vts))
      # Invalidated targets are a subset of relevant targets: get the context for this one.
      compile_target = vts.targets[0]
      compile_context = compile_contexts[compile_target]

      def create_work_for_vts(vts, compile_context, compile_classpaths,
                       extra_compile_time_classpath, idx):
        def work():
          progress_message = 'target {} of {}'.format(idx + 1, invalid_vts_count)
          upstream_analysis = dict(self._upstream_analysis(compile_contexts,
                                                           compile_context.target))
          cp_entries = self._compute_classpath_entries(compile_classpaths, compile_context,
                                                       extra_compile_time_classpath)
          compile_vts(vts,
                      compile_context.sources,
                      compile_context.analysis_file,
                      upstream_analysis,
                      cp_entries,
                      compile_context.classes_dir,
                      progress_message)

          # Update the products with the latest classes.
          register_vts([compile_context])

          # Kick off the background artifact cache write.
          if update_artifact_cache_vts_work:
            self._write_to_artifact_cache(vts, compile_context, update_artifact_cache_vts_work)
        return work

      target_subgraph = self.context.build_graph \
        .transitive_subgraph_of_addresses([compile_target.address])
      dependencies = [target for target in target_subgraph
                      if target in invalid_targets and target != compile_target]

      exec_graph.schedule(self.exec_graph_key_for_target(compile_target),
                          create_work_for_vts(vts, compile_context, compile_classpaths,
                                              extra_compile_time_classpath, idx),
                          [self.exec_graph_key_for_target(target) for target in dependencies],
                          # If compilation and analysis work succeeds, validate the vts.
                          # Otherwise, fail it.
                          on_success=vts.update,
                          on_failure=vts.force_invalidate)

    try:
      exec_graph.execute()
    except ExecutionGraph.ExecutionFailure:
      raise TaskError("Compilation failure")

  def compute_resource_mapping(self, compile_contexts):
    return ResourceMapping(self._classes_dir)

  def post_process_cached_vts(self, cached_vts):
    """Localizes the fetched analysis for targets we found in the cache.

    This is the complement of `_write_to_artifact_cache`.
    """
    compile_contexts = []
    for vt in cached_vts:
      for target in vt.targets:
        compile_contexts.append(self.compile_context(target))

    for compile_context in compile_contexts:
      portable_analysis_file = JvmCompileStrategy._portable_analysis_for_target(
          self._analysis_dir, compile_context.target)
      if os.path.exists(portable_analysis_file):
        self._analysis_tools.localize(portable_analysis_file, compile_context.analysis_file)

  def _write_to_artifact_cache(self, vts, compile_context, get_update_artifact_cache_work):
    assert len(vts.targets) == 1
    assert vts.targets[0] == compile_context.target

    # Noop if the target is uncacheable.
    if (compile_context.target.has_label('no_cache')):
      return
    vt = vts.versioned_targets[0]

    # Set up args to relativize analysis in the background.
    # TODO: GlobalStrategy puts portable analysis in a tmp directory... shall we?
    portable_analysis_file = JvmCompileStrategy._portable_analysis_for_target(
        self._analysis_dir, compile_context.target)
    relativize_args_tuple = (compile_context.analysis_file, portable_analysis_file)

    # Compute the classes and resources for this target.
    artifacts = []
    resources_by_target = self.context.products.get_data('resources_by_target')
    if resources_by_target is not None:
      for _, paths in resources_by_target[compile_context.target].abs_paths():
        artifacts.extend(paths)
    for dirpath, _, filenames in safe_walk(compile_context.classes_dir):
      artifacts.extend([os.path.join(dirpath, f) for f in filenames])

    # Get the 'work' that will publish these artifacts to the cache.
    # NB: the portable analysis_file won't exist until we finish.
    vts_artifactfiles_pair = (vt, artifacts + [portable_analysis_file])
    update_artifact_cache_work = get_update_artifact_cache_work([vts_artifactfiles_pair])

    # And execute it.
    if update_artifact_cache_work:
      work_chain = [
        Work(self._analysis_tools.relativize, [relativize_args_tuple], 'relativize'),
        update_artifact_cache_work
      ]
      self.context.submit_background_work_chain(work_chain, parent_workunit_name='cache')
