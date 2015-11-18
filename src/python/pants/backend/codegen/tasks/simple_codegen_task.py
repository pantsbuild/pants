# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import os
from abc import abstractmethod
from collections import OrderedDict

from twitter.common.collections import OrderedSet

from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnitLabel
from pants.build_graph.address import Address
from pants.build_graph.address_lookup_error import AddressLookupError
from pants.task.task import Task
from pants.util.dirutil import fast_relpath, safe_delete, safe_walk


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
    register('--allow-dups', action='store_true', default=False, fingerprint=True,
              help='Allow multiple targets specifying the same sources. If duplicates are '
                   'allowed, the logic of find_sources will associate generated sources with '
                   'the least-dependent targets that generate them.',
              advanced=True)

  @classmethod
  def get_fingerprint_strategy(cls):
    """Override this method to use a fingerprint strategy other than the default one.

    :return: a fingerprint strategy, or None to use the default strategy.
    """
    return None

  @property
  def cache_target_dirs(self):
    return True

  @property
  def validate_sources_present(self):
    """A property indicating whether input targets require sources.

    If targets should have sources, the `--allow-empty` flag indicates whether it is a
    warning or an error for sources to be missing.
    """
    return True

  def synthetic_target_extra_dependencies(self, target, target_workdir):
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

  def _do_validate_sources_present(self, target):
    """Checks whether sources is empty, and either raises a TaskError or just returns False.

    The specifics of this behavior are defined by whether the user sets --allow-empty to True/False:
    --allow-empty=False will result in a TaskError being raised in the event of an empty source
    set. If --allow-empty=True, this method will just return false and log a warning.

    Shared for all SimpleCodegenTask subclasses to help keep errors consistent and descriptive.

    :param target: Target to validate.
    :return: True if sources is not empty, False otherwise.
    """
    if not self.validate_sources_present:
      return True
    sources = target.sources_relative_to_buildroot()
    if not sources:
      message = ('Target {} has no sources.'.format(target.address.spec))
      if not self.get_options().allow_empty:
        raise TaskError(message)
      else:
        logging.warn(message)
        return False
    return True

  def _get_synthetic_address(self, target, target_workdir):
    synthetic_name = target.id
    sources_rel_path = os.path.relpath(target_workdir, get_buildroot())
    synthetic_address = Address(sources_rel_path, synthetic_name)
    return synthetic_address

  def execute(self):
    with self.invalidated(self.codegen_targets(),
                          invalidate_dependents=True,
                          fingerprint_strategy=self.get_fingerprint_strategy()) as invalidation_check:
      with self.context.new_workunit(name='execute', labels=[WorkUnitLabel.MULTITOOL]):
        for vt in invalidation_check.all_vts:
          # Build the target and handle duplicate sources.
          if not vt.valid:
            if self._do_validate_sources_present(vt.target):
              self.execute_codegen(vt.target, vt.results_dir)
              self._handle_duplicate_sources(vt.target, vt.results_dir)
            vt.update()
          # And inject a synthetic target to represent it.
          self._inject_synthetic_target(vt.target, vt.results_dir)

  def _inject_synthetic_target(self, target, target_workdir):
    """Create, inject, and return a synthetic target for the given target and workdir.

    :param target: The target to inject a synthetic target for.
    :param target_workdir: The work directory containing the generated code for the target.
    """
    synthetic_target = self.context.add_new_target(
      address=self._get_synthetic_address(target, target_workdir),
      target_type=self.synthetic_target_type(target),
      dependencies=self.synthetic_target_extra_dependencies(target, target_workdir),
      sources=list(self.find_sources(target, target_workdir)),
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

    return synthetic_target

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

  def find_sources(self, target, target_workdir):
    """Determines what sources were generated by the target after the fact.

    This is done by searching the directory where this target's code was generated.

    :param Target target: the target for which to find generated sources.
    :param path target_workdir: directory containing sources for the target.
    :return: A set of filepaths relative to the target_workdir.
    :rtype: OrderedSet
    """
    return OrderedSet(self._find_sources_in_workdir(target_workdir))

  def _find_sources_in_workdir(self, target_workdir):
    """Returns relative sources contained in the given target_workdir."""
    for root, _, files in safe_walk(target_workdir):
      rel_root = fast_relpath(root, target_workdir)
      for name in files:
        yield os.path.join(rel_root, name)

  def _handle_duplicate_sources(self, target, target_workdir):
    """Handles duplicate sources generated by the given gen target by either failure or deletion.

    This method should be called after all dependencies have been injected into the graph, but
    before injecting the synthetic version of this target.

    NB(gm): Some code generators may re-generate code that their dependent libraries generate.
    This results in targets claiming to generate sources that they really don't, so we try to
    filter out sources that were actually generated by dependencies of the target. This causes
    the code generated by the dependencies to 'win' over the code generated by dependees. By
    default, this behavior is disabled, and duplication in generated sources will raise a
    TaskError. This is controlled by the --allow-dups flag.
    """
    # Compute the raw sources owned by this target.
    by_target = self.find_sources(target, target_workdir)

    # Walk dependency gentargets and record any sources owned by those targets that are also
    # owned by this target.
    duplicates_by_target = OrderedDict()
    def record_duplicates(dep):
      if dep == target or not self.is_gentarget(dep.concrete_derived_from):
        return
      duped_sources = [s for s in dep.sources_relative_to_source_root() if s in by_target]
      if duped_sources:
        duplicates_by_target[dep] = duped_sources
    target.walk(record_duplicates)

    # If there were no dupes, we're done.
    if not duplicates_by_target:
      return

    # If there were duplicates warn or error.
    messages = ['{target} generated sources that had already been generated by dependencies.'
                .format(target=target.address.spec)]
    for dep, duped_sources in duplicates_by_target.items():
      messages.append('\t{} also generated:'.format(dep.concrete_derived_from.address.spec))
      messages.extend(['\t\t{}'.format(source) for source in duped_sources])
    message = '\n'.join(messages)
    if self.get_options().allow_dups:
      logger.warn(message)
    else:
      raise self.DuplicateSourceError(message)

    # Finally, remove duplicates from the workdir. This prevents us from having to worry
    # about them during future incremental compiles.
    for dep, duped_sources in duplicates_by_target.items():
      for duped_source in duped_sources:
        safe_delete(os.path.join(target_workdir, duped_source))

  class DuplicateSourceError(TaskError):
    """A target generated the same code that was generated by one of its dependencies.

    This is only thrown when --allow-dups=False.
    """
