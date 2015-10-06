# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import sys
from collections import defaultdict
from contextlib import contextmanager

from twitter.common.collections import OrderedSet

from pants.base.build_environment import get_buildroot, get_scm
from pants.base.source_root import SourceRoot
from pants.base.worker_pool import SubprocPool
from pants.base.workunit import WorkUnitLabel
from pants.build_graph.build_graph import BuildGraph
from pants.build_graph.target import Target
from pants.goal.products import Products
from pants.goal.workspace import ScmWorkspace
from pants.process.pidlock import OwnerPrintingPIDLockFile
from pants.reporting.report import Report


class Context(object):
  """Contains the context for a single run of pants.

  Task implementations can access configuration data from pants.ini and any flags they have exposed
  here as well as information about the targets involved in the run.

  Advanced uses of the context include adding new targets to it for upstream or downstream goals to
  operate on and mapping of products a goal creates to the targets the products are associated with.
  """

  class Log(object):
    """A logger facade that logs into the pants reporting framework."""

    def __init__(self, run_tracker):
      self._run_tracker = run_tracker

    def debug(self, *msg_elements):
      self._run_tracker.log(Report.DEBUG, *msg_elements)

    def info(self, *msg_elements):
      self._run_tracker.log(Report.INFO, *msg_elements)

    def warn(self, *msg_elements):
      self._run_tracker.log(Report.WARN, *msg_elements)

    def error(self, *msg_elements):
      self._run_tracker.log(Report.ERROR, *msg_elements)

    def fatal(self, *msg_elements):
      self._run_tracker.log(Report.FATAL, *msg_elements)

  # TODO: Figure out a more structured way to construct and use context than this big flat
  # repository of attributes?
  def __init__(self, options, run_tracker, target_roots,
               requested_goals=None, target_base=None, build_graph=None,
               build_file_parser=None, address_mapper=None, console_outstream=None, scm=None,
               workspace=None, spec_excludes=None, invalidation_report=None):
    self._options = options
    self.build_graph = build_graph
    self.build_file_parser = build_file_parser
    self.address_mapper = address_mapper
    self.run_tracker = run_tracker
    self._log = self.Log(run_tracker)
    self._target_base = target_base or Target
    self._products = Products()
    self._buildroot = get_buildroot()
    self._lock = OwnerPrintingPIDLockFile(os.path.join(self._buildroot, '.pants.run'))
    self._java_sysprops = None  # Computed lazily.
    self.requested_goals = requested_goals or []
    self._console_outstream = console_outstream or sys.stdout
    self._scm = scm or get_scm()
    self._workspace = workspace or (ScmWorkspace(self._scm) if self._scm else None)
    self._spec_excludes = spec_excludes
    self._replace_targets(target_roots)
    self._synthetic_targets = defaultdict(list)
    self._invalidation_report = invalidation_report

  @property
  def options(self):
    """Returns the new-style options."""
    return self._options

  @property
  def log(self):
    """Returns the preferred logger for goals to use."""
    return self._log

  @property
  def products(self):
    """Returns the Products manager for the current run."""
    return self._products

  @property
  def target_roots(self):
    """Returns the targets specified on the command line.

    This set is strictly a subset of all targets in play for the run as returned by self.targets().
    Note that for a command line invocation that uses wildcard selectors : or ::, the targets
    globbed by the wildcards are considered to be target roots.
    """
    return self._target_roots

  @property
  def console_outstream(self):
    """Returns the output stream to write console messages to."""
    return self._console_outstream

  @property
  def scm(self):
    """Returns the current workspace's scm, if any."""
    return self._scm

  @property
  def workspace(self):
    """Returns the current workspace, if any."""
    return self._workspace

  @property
  def spec_excludes(self):
    return self._spec_excludes

  @property
  def invalidation_report(self):
    return self._invalidation_report

  def __str__(self):
    ident = Target.identify(self.targets())
    return 'Context(id:{}, targets:{})'.format(ident, self.targets())

  def submit_background_work_chain(self, work_chain, parent_workunit_name=None):
    background_root_workunit = self.run_tracker.get_background_root_workunit()
    if parent_workunit_name:
      # We have to keep this workunit alive until all its child work is done, so
      # we manipulate the context manually instead of using it as a contextmanager.
      # This is slightly funky, but the with-context usage is so pervasive and
      # useful elsewhere that it's worth the funkiness in this one place.
      workunit_parent_ctx = self.run_tracker.new_workunit_under_parent(
        name=parent_workunit_name, labels=[WorkUnitLabel.MULTITOOL], parent=background_root_workunit)
      workunit_parent = workunit_parent_ctx.__enter__()
      done_hook = lambda: workunit_parent_ctx.__exit__(None, None, None)
    else:
      workunit_parent = background_root_workunit  # Run directly under the root.
      done_hook = None
    self.run_tracker.background_worker_pool().submit_async_work_chain(
      work_chain, workunit_parent=workunit_parent, done_hook=done_hook)

  def background_worker_pool(self):
    """Returns the pool to which tasks can submit background work."""
    return self.run_tracker.background_worker_pool()

  def subproc_map(self, f, items):
    """Map function `f` over `items` in subprocesses and return the result.

      :param f: A multiproc-friendly (importable) work function.
      :param items: A iterable of pickleable arguments to f.
    """
    try:
      # Pool.map (and async_map().get() w/o timeout) can miss SIGINT.
      # See: http://stackoverflow.com/a/1408476, http://bugs.python.org/issue8844
      # Instead, we map_async(...), wait *with a timeout* until ready, then .get()
      # NB: in 2.x, wait() with timeout wakes up often to check, burning CPU. Oh well.
      res = SubprocPool.foreground().map_async(f, items)
      while not res.ready():
        res.wait(60)  # Repeatedly wait for up to a minute.
        if not res.ready():
          self.log.debug('subproc_map result still not ready...')
      return res.get()
    except KeyboardInterrupt:
      SubprocPool.shutdown(True)
      raise

  @contextmanager
  def new_workunit(self, name, labels=None, cmd='', log_config=None):
    """Create a new workunit under the calling thread's current workunit."""
    with self.run_tracker.new_workunit(name=name, labels=labels, cmd=cmd, log_config=log_config) as workunit:
      yield workunit

  def acquire_lock(self):
    """ Acquire the global lock for the root directory associated with this context. When
    a goal requires serialization, it will call this to acquire the lock.
    """
    if self.options.for_global_scope().lock:
      if not self._lock.i_am_locking():
        self._lock.acquire()

  def release_lock(self):
    """Release the global lock if it's held.
    Returns True if the lock was held before this call.
    """
    if not self._lock.i_am_locking():
      return False
    else:
      self._lock.release()
      return True

  def is_unlocked(self):
    """Whether the global lock object is actively holding the lock."""
    return not self._lock.i_am_locking()

  def _replace_targets(self, target_roots):
    # Replaces all targets in the context with the given roots and their transitive dependencies.
    #
    # If another task has already retrieved the current targets, mutable state may have been
    # initialized somewhere, making it now unsafe to replace targets. Thus callers of this method
    # must know what they're doing!
    #
    # TODO(John Sirois): This currently has 0 uses (outside ContextTest) in pantsbuild/pants and
    # only 1 remaining known use case in the Foursquare codebase that will be able to go away with
    # the post RoundEngine engine - kill the method at that time.
    self._target_roots = list(target_roots)

  def add_new_target(self, address, target_type, target_base=None, dependencies=None,
                     derived_from=None, **kwargs):
    """Creates a new target, adds it to the context and returns it.

    This method ensures the target resolves files against the given target_base, creating the
    directory if needed and registering a source root.
    """
    target_base = os.path.join(get_buildroot(), target_base or address.spec_path)
    if not os.path.exists(target_base):
      os.makedirs(target_base)
    if not SourceRoot.find_by_path(target_base):
      SourceRoot.register(target_base)
    if dependencies:
      dependencies = [dep.address for dep in dependencies]

    self.build_graph.inject_synthetic_target(address=address,
                                             target_type=target_type,
                                             dependencies=dependencies,
                                             derived_from=derived_from,
                                             **kwargs)
    new_target = self.build_graph.get_target(address)

    if derived_from:
      self._synthetic_targets[derived_from].append(new_target)

    return new_target

  def targets(self, predicate=None, postorder=False):
    """Selects targets in-play in this run from the target roots and their transitive dependencies.

    Also includes any new synthetic targets created from the target roots or their transitive
    dependencies during the course of the run.

    :param predicate: If specified, the predicate will be used to narrow the scope of targets
                      returned.
    :param bool postorder: `True` to gather transitive dependencies with a postorder traversal;
                          `False` or preorder by default.
    :returns: A list of matching targets.
    """
    target_set = self._collect_targets(self.target_roots, postorder=postorder)

    synthetics = OrderedSet()
    for derived_from, synthetic_targets in self._synthetic_targets.items():
      if derived_from in target_set or derived_from in synthetics:
        synthetics.update(synthetic_targets)

    synthetic_set = self._collect_targets(synthetics, postorder=postorder)

    target_set.update(synthetic_set)

    return filter(predicate, target_set)

  def _collect_targets(self, root_targets, postorder=False):
    addresses = [target.address for target in root_targets]
    target_set = self.build_graph.transitive_subgraph_of_addresses(addresses,
                                                                   postorder=postorder)
    return target_set

  def dependents(self, on_predicate=None, from_predicate=None):
    """Returns  a map from targets that satisfy the from_predicate to targets they depend on that
      satisfy the on_predicate.
    """
    core = set(self.targets(on_predicate))
    dependees = defaultdict(set)
    for target in self.targets(from_predicate):
      for dependency in target.dependencies:
        if dependency in core:
          dependees[target].add(dependency)
    return dependees

  def resolve(self, spec):
    """Returns an iterator over the target(s) the given address points to."""
    return self.build_graph.resolve(spec)

  def scan(self, root=None):
    """Scans and parses all BUILD files found under ``root``.

    Only BUILD files found under ``root`` are parsed as roots in the graph, but any dependencies of
    targets parsed in the root tree's BUILD files will be followed and this may lead to BUILD files
    outside of ``root`` being parsed and included in the returned build graph.

    :param string root: The path to scan; by default, the build root.
    :returns: A new build graph encapsulating the targets found.
    """
    build_graph = BuildGraph(self.address_mapper)
    for address in self.address_mapper.scan_addresses(root, spec_excludes=self.spec_excludes):
      build_graph.inject_address_closure(address)
    return build_graph
