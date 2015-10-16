# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import os
from abc import abstractmethod

from twitter.common.collections import OrderedSet

from pants.backend.core.tasks.task import Task
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnitLabel
from pants.build_graph.address import Address
from pants.build_graph.address_lookup_error import AddressLookupError
from pants.build_graph.build_graph import sort_targets
from pants.util.dirutil import fast_relpath, safe_rmtree, safe_walk
from pants.util.memo import memoized_property
from pants.util.meta import AbstractClass


logger = logging.getLogger(__name__)


class SimpleCodegenTask(Task):
  """A base-class for code generation for a single target language."""

  @classmethod
  def product_types(cls):
    # NB(gmalmquist): This is a hack copied from the old CodeGen base class to get the round manager
    # to properly run codegen before resolve and compile. It would be more correct to just have each
    # individual codegen class declare what languages it generates, but would cause problems with
    # scala. See https://rbcommons.com/s/twitter/r/2540/.
    return ['java', 'scala', 'python']

  @classmethod
  def register_options(cls, register):
    super(SimpleCodegenTask, cls).register_options(register)
    register('--allow-empty', action='store_true', default=True, fingerprint=True,
             help='Skip targets with no sources defined.',
             advanced=True)
    register('--strategy', fingerprint=True, default=None,
              deprecated_version='0.0.57',
              deprecated_hint='Only isolated codegen is supported.',
              help='Selects the compilation strategy to use. The "global" strategy uses a shared '
                  'global directory for all generated code, and the "isolated" strategy uses '
                  'per-target codegen directories.',
              advanced=True)
    register('--allow-dups', action='store_true', default=False, fingerprint=True,
              help='Allow multiple targets specifying the same sources '
                   'strategy. If duplicates are allowed, the logic of find_sources in '
                   'IsolatedCodegenStrategy will associate generated sources with '
                   'least-dependent targets that generate them.',
              advanced=True)

  @classmethod
  def get_fingerprint_strategy(cls):
    """Override this method to use a fingerprint strategy other than the default one.

    :return: a fingerprint strategy, or None to use the default strategy.
    """
    return None

  def __init__(self, *args, **kwargs):
    super(SimpleCodegenTask, self).__init__(*args, **kwargs)
    # NOTE(gm): This memoization yields a ~10% performance increase on my machine.
    self._generated_sources_cache = {}

  @property
  def cache_target_dirs(self):
    return True

  def synthetic_target_extra_dependencies(self, target):
    """Gets any extra dependencies generated synthetic targets should have.

    This method is optional for subclasses to implement, because some code generators may have no
    extra dependencies.
    :param Target target: the Target from which we are generating a synthetic Target. E.g., 'target'
    might be a JavaProtobufLibrary, whose corresponding synthetic Target would be a JavaLibrary.
    It may not be necessary to use this parameter depending on the details of the subclass.
    :return: a list of dependencies.
    """
    return []

  def synthetic_target_type_by_target(self, target):
    """The type of target this codegen task generates.

    For example, the target type for JaxbGen would simply be JavaLibrary.
    :return: a type (class) that inherits from Target.
    """
    raise NotImplementedError

  def synthetic_target_type(self, target):
    """The type of target this codegen task generates.

    For example, the target type for JaxbGen would simply be JavaLibrary.
    :return: a type (class) that inherits from Target.
    """
    raise NotImplementedError

  def is_gentarget(self, target):
    """Predicate which determines whether the target in question is relevant to this codegen task.

    E.g., the JaxbGen task considers JaxbLibrary targets to be relevant, and nothing else.
    :param Target target: The target to check.
    :return: True if this class can generate code for the given target, False otherwise.
    """
    raise NotImplementedError

  def codegen_targets(self):
    """Finds codegen targets in the dependency graph.

    :return: an iterable of dependency targets.
    """
    return self.context.targets(self.is_gentarget)

  def validate_sources_present(self, sources, targets):
    """Checks whether sources is empty, and either raises a TaskError or just returns False.

    The specifics of this behavior are defined by whether the user sets --allow-empty to True/False:
    --allow-empty=False will result in a TaskError being raised in the event of an empty source
    set. If --allow-empty=True, this method will just return false and log a warning.

    Shared for all SimpleCodegenTask subclasses to help keep errors consistent and descriptive.
    :param sources: the sources from the given targets.
    :param targets: the targets the sources are from, included just for error message generation.
    :return: True if sources is not empty, False otherwise.
    """
    if not sources:
      formatted_targets = '\n'.join([t.address.spec for t in targets])
      message = ('Had {count} targets but no sources?\n targets={targets}'
                 .format(count=len(targets), targets=formatted_targets))
      if not self.get_options().allow_empty:
        raise TaskError(message)
      else:
        logging.warn(message)
        return False
    return True

  def get_synthetic_address(self, target, target_workdir):
    synthetic_name = target.id
    sources_rel_path = os.path.relpath(target_workdir, get_buildroot())
    synthetic_address = Address(sources_rel_path, synthetic_name)
    return synthetic_address

  def execute(self):
    with self.invalidated(self.codegen_targets(),
                          invalidate_dependents=True,
                          fingerprint_strategy=self.get_fingerprint_strategy()) as invalidation_check:
      target_workdirs = {vt.target: vt.results_dir for vt in invalidation_check.all_vts}
      for vt in invalidation_check.all_vts:
        target = vt.target
        if not vt.valid:
          with self.context.new_workunit(name=target.address.spec):
            self.execute_codegen(target, vt.results_dir)

        target_workdir = vt.results_dir
        raw_generated_sources = list(self.find_sources(target, target_workdirs))
        # Make the sources robust regardless of whether subclasses return relative paths, or
        # absolute paths that are subclasses of the workdir.
        generated_sources = [src if src.startswith(target_workdir)
                             else os.path.join(target_workdir, src)
                             for src in raw_generated_sources]
        relative_generated_sources = [os.path.relpath(src, target_workdir)
                                      for src in generated_sources]

        synthetic_target = self.context.add_new_target(
          address=self.get_synthetic_address(target, target_workdir),
          target_type=self.synthetic_target_type(target),
          dependencies=self.synthetic_target_extra_dependencies(target),
          sources=relative_generated_sources,
          derived_from=target,

          # TODO(John Sirois): This assumes - currently, a JvmTarget or PythonTarget which both
          # happen to have this attribute for carrying publish metadata but share no interface
          # that defines this canonical property.  Lift up an interface and check for it or else
          # add a way for SimpleCodeGen subclasses to specify extra attribute names that should be
          # copied over from the target to its derived target.
          provides=target.provides,
        )

        build_graph = self.context.build_graph

        # NB(pl): This bypasses the convenience function (Target.inject_dependency) in order
        # to improve performance.  Note that we can walk the transitive dependee subgraph once
        # for transitive invalidation rather than walking a smaller subgraph for every single
        # dependency injected.
        for dependent_address in build_graph.dependents_of(target.address):
          build_graph.inject_dependency(
            dependent=dependent_address,
            dependency=synthetic_target.address,
          )
        # NB(pl): See the above comment.  The same note applies.
        for concrete_dependency_address in build_graph.dependencies_of(target.address):
          build_graph.inject_dependency(
            dependent=synthetic_target.address,
            dependency=concrete_dependency_address,
          )
        build_graph.walk_transitive_dependee_graph(
          build_graph.dependencies_of(target.address),
          work=lambda t: t.mark_transitive_invalidation_hash_dirty(),
        )

        if target in self.context.target_roots:
          self.context.target_roots.append(synthetic_target)

  def resolve_deps(self, unresolved_deps):
    deps = OrderedSet()
    for dep in unresolved_deps:
      try:
        deps.update(self.context.resolve(dep))
      except AddressLookupError as e:
        raise AddressLookupError('{message}\n  on dependency {dep}'.format(message=e, dep=dep))
    return deps

  @abstractmethod
  def execute_codegen(self, target, target_workdir):
    """Generate code for the given target.

    :param target: A target to generate code for
    :param target_workdir: A clean directory into which to generate code
    """

  def find_sources(self, target, target_workdirs):
    """Determines what sources were generated by the target after the fact.

    This is done by searching the directory where this target's code was generated. This is only
    possible because each target has its own unique directory in this CodegenStrategy.
    :param Target target: the target for which to find generated sources.
    :param dict target_workdirs: dict mapping targets (for this context) to their workdirs
    :return: a set of relative filepaths.
    :rtype: OrderedSet
    """
    return self._find_sources_strictly_generated_by_target(target, target_workdirs)

  def _find_sources_generated_by_target(self, target, target_workdir):
    if target.id in self._generated_sources_cache:
      for source in self._generated_sources_cache[target.id]:
        yield source
    else:
      for root, dirs, files in safe_walk(target_workdir):
        for name in files:
          yield os.path.join(root, name)

  def _find_sources_generated_by_dependencies(self, target, target_workdirs):
    sources = OrderedSet()

    def add_sources(dep):
      dep_workdir = target_workdirs[dep]
      if dep is not target:
        dep_sources = self._find_sources_generated_by_target(dep, dep_workdir)
        dep_sources = [fast_relpath(source, dep_workdir) for source in dep_sources]
        sources.update(dep_sources)
    target.walk(add_sources)
    return sources

  def _find_sources_strictly_generated_by_target(self, target, target_workdirs):
    # NB(gm): Some code generators may re-generate code that their dependent libraries generate.
    # This results in targets claiming to generate sources that they really don't, so we try to
    # filter out sources that were actually generated by dependencies of the target. This causes
    # the code generated by the dependencies to 'win' over the code generated by dependees. By
    # default, this behavior is disabled, and duplication in generated sources will raise a
    # TaskError. This is controlled by the --allow-dups flag.
    if target.id in self._generated_sources_cache:
      return self._generated_sources_cache[target.id]
    target_workdir = target_workdirs[target]
    by_target = OrderedSet(self._find_sources_generated_by_target(target, target_workdir))
    by_dependencies = self._find_sources_generated_by_dependencies(target, target_workdirs)
    strict = [s for s in by_target if (fast_relpath(s, target_workdir) not in by_dependencies)]
    if len(strict) != len(by_target):
      messages = ['{target} generated sources that had already been generated by dependencies.'
                  .format(target=target.address.spec)]
      # Doing some extra work for the sake of helpful error messages.
      duplicate_sources = set([fast_relpath(source, target_workdir)
                            for source in sorted(set(by_target) - set(strict))])
      duplicates_by_targets = {}

      def record_duplicates(dep):
        if dep == target:
          return
        dep_workdir = target_workdirs[dep]
        sources = [fast_relpath(s, dep_workdir)
                   for s in self._find_sources_generated_by_target(dep, dep_workdir)]
        sources = [s for s in sources if s in duplicate_sources]
        if sources:
          duplicates_by_targets[dep] = sources

      target.walk(record_duplicates)
      for dependency in sorted(duplicates_by_targets, key=lambda t: t.address.spec):
        messages.append('\t{} also generated:'.format(dependency.address.spec))
        messages.extend(['\t\t{}'.format(source) for source in duplicates_by_targets[dependency]])
      message = '\n'.join(messages)
      if self.get_options().allow_dups:
        logger.warn(message)
      else:
        raise self.DuplicateSourceError(message)

    self._generated_sources_cache[target.id] = strict
    return strict

  class DuplicateSourceError(TaskError):
    """A target generated the same code that was generated by one of its dependencies.

    This is only thrown when --allow-dups=False.
    """
