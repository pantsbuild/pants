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
from pants.base.address import Address
from pants.base.address_lookup_error import AddressLookupError
from pants.base.build_environment import get_buildroot
from pants.base.dep_lookup_error import DepLookupError
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnitLabel
from pants.build_graph.build_graph import sort_targets
from pants.util.dirutil import safe_rmtree, safe_walk
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
    strategy_names = [strategy.name() for strategy in cls.supported_strategy_types()]
    if cls.forced_codegen_strategy() is None:
      register('--strategy', choices=strategy_names, fingerprint=True,
               default=strategy_names[0],
               help='Selects the compilation strategy to use. The "global" strategy uses a shared '
                    'global directory for all generated code, and the "isolated" strategy uses '
                    'per-target codegen directories.',
               advanced=True)
    if 'isolated' in strategy_names:
      register('--allow-dups', action='store_true', default=False, fingerprint=True,
               help='Allow multiple targets specifying the same sources when using the isolated '
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

  def execute_codegen(self, invalid_targets):
    """Generated code for the given list of targets.

    :param invalid_targets: an iterable of targets (a subset of codegen_targets()).
    """
    raise NotImplementedError

  def codegen_targets(self):
    """Finds codegen targets in the dependency graph.

    :return: an iterable of dependency targets.
    """
    return self.context.targets(self.is_gentarget)

  @classmethod
  def supported_strategy_types(cls):
    """The CodegenStrategy subclasses that this codegen task supports.

    This list is used to generate the options for the --strategy flag. The first item in the list
    is used as the default value.

    By default, this only supports the IsolatedCodegenStrategy. Subclasses which desire global
    generation should subclass the GlobalCodegenStrategy.
    :return: the list of types (classes, not instances) that extend from CodegenStrategy.
    :rtype: list
    """
    return [cls.IsolatedCodegenStrategy]

  @classmethod
  def forced_codegen_strategy(cls):
    """If only a single codegen strategy is supported, returns its name.

    This value of this function is automatically computed from the supported_strategy_types.
    :return: the forced code generation strategy, or None if multiple options are supported.
    """
    strategy_types = cls.supported_strategy_types()
    if not strategy_types:
      raise TaskError("{} doesn't support any codegen strategies.".format(cls.__name__))
    if len(strategy_types) == 1:
      return strategy_types[0].name()
    return None

  @classmethod
  def _codegen_strategy_map(cls):
    """Returns a dict which maps names to codegen strategy types.

    This is generated from the supported_strategy_types list.
    """
    return {strategy.name(): strategy for strategy in cls.supported_strategy_types()}

  def _codegen_strategy_for_name(self, name):
    strategy_type_map = self._codegen_strategy_map()
    if name not in strategy_type_map:
      raise self.UnsupportedStrategyError('Unsupported codegen strategy "{}".'.format(name))
    return strategy_type_map[name](self)

  @memoized_property
  def codegen_strategy(self):
    """Returns the codegen strategy object used by this codegen.

    This is controlled first by the forced_codegen_strategy method, then by user-specified
    options if the former returns None.

    If you just want the name ('global' or 'isolated') of the strategy, use codegen_strategy.name().

    :return: the codegen strategy object.
    :rtype: SimpleCodegenTask.CodegenStrategy
    """
    strategy = self.forced_codegen_strategy()
    if strategy is None:
      strategy = self.get_options().strategy
    return self._codegen_strategy_for_name(strategy)

  def codegen_workdir(self, target):
    """The path to the directory code should be generated in.

    E.g., this might be something like /home/user/repo/.pants.d/gen/jaxb/...
    Generally, subclasses should not need to override this method. If they do, it is crucial that
    the implementation is /deterministic/ -- that is, the return value of this method should always
    be the same for the same input target.
    :param Target target: the codegen target (e.g., a java_protobuf_library).
    :return: The absolute file path.
    """
    return os.path.join(self.workdir, self.codegen_strategy.codegen_workdir_suffix(target))

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

  def get_synthetic_address(self,target):
    target_workdir = self.codegen_workdir(target)
    synthetic_name = target.id
    sources_rel_path = os.path.relpath(target_workdir, get_buildroot())
    synthetic_address = Address(sources_rel_path, synthetic_name)
    return synthetic_address

  def execute(self):
    targets = self.codegen_targets()
    with self.invalidated(targets,
                          invalidate_dependents=True,
                          fingerprint_strategy=self.get_fingerprint_strategy()) as invalidation_check:
      invalid_targets = OrderedSet()
      for vts in invalidation_check.invalid_vts:
        invalid_targets.update(vts.targets)
      self.codegen_strategy.execute_codegen(invalid_targets)

      invalid_vts_by_target = dict([(vt.target, vt) for vt in invalidation_check.invalid_vts])
      vts_artifactfiles_pairs = []

      for target in targets:
        target_workdir = self.codegen_workdir(target)
        raw_generated_sources = list(self.codegen_strategy.find_sources(target))
        # Make the sources robust regardless of whether subclasses return relative paths, or
        # absolute paths that are subclasses of the workdir.
        generated_sources = [src if src.startswith(target_workdir)
                             else os.path.join(target_workdir, src)
                             for src in raw_generated_sources]
        relative_generated_sources = [os.path.relpath(src, target_workdir)
                                      for src in generated_sources]

        self.target = self.context.add_new_target(
          address=self.get_synthetic_address(target),
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
        synthetic_target = self.target

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
        if target in invalid_vts_by_target:
          vts_artifactfiles_pairs.append((invalid_vts_by_target[target], generated_sources))

      if self.artifact_cache_writes_enabled():
        self.update_artifact_cache(vts_artifactfiles_pairs)

  def resolve_deps(self, unresolved_deps):
    deps = OrderedSet()
    for dep in unresolved_deps:
      try:
        deps.update(self.context.resolve(dep))
      except AddressLookupError as e:
        raise DepLookupError('{message}\n  on dependency {dep}'.format(message=e, dep=dep))
    return deps

  class CodegenStrategy(AbstractClass):
    """Abstract strategies for running codegen.

    Includes predicting generated sources, partitioning targets for execution, etc.
    """

    @classmethod
    def name(self):
      """The name of this strategy (eg, 'isolated').

      This is used for generating the list of valid options for the --strategy flag.
      """
      raise NotImplementedError

    def _do_execute_codegen(self, targets):
      """Invokes the task's execute_codegen on the targets """
      try:
        self._task.execute_codegen(targets)
      except Exception as ex:
        for target in targets:
          self._task.context.log.error('Failed to generate target: {}'.format(target.address.spec))
        raise TaskError(ex)

    @abstractmethod
    def execute_codegen(self, targets):
      """Invokes _do_execute_codegen on the targets.

      Subclasses decide how the targets are partitioned before being sent to the task's
      execute_codegen method.
      :targets: a set of targets.
      """

    @abstractmethod
    def find_sources(self, target):
      """Finds (or predicts) the sources generated by the given target."""

    @abstractmethod
    def codegen_workdir_suffix(self, target):
      """The working directory suffix for the given target's generated code."""

    def __str__(self):
      return self.name()

  class GlobalCodegenStrategy(CodegenStrategy):
    """Code generation strategy which generates all code together, in base directory."""

    def __init__(self, task):
      self._task = task

    @classmethod
    def name(cls):
      return 'global'

    def execute_codegen(self, targets):
      with self._task.context.new_workunit(name='execute', labels=[WorkUnitLabel.MULTITOOL]):
        self._do_execute_codegen(targets)

    @abstractmethod
    def find_sources(self, target):
      """Predicts what sources the codegen target will generate.

      The exact implementation of this is left to the GlobalCodegenStrategy subclass.
      :param Target target: the target for which to find generated sources.
      :return: a set of relative filepaths.
      :rtype: OrderedSet
      """

    def codegen_workdir_suffix(self, target):
      return self.name()

  class IsolatedCodegenStrategy(CodegenStrategy):
    """Code generate strategy which generates the code for each target separately.

    Code is generated in a unique parent directory per target.
    """

    def __init__(self, task):
      self._task = task
      # NOTE(gm): This memoization yields a ~10% performance increase on my machine.
      self._generated_sources_cache = {}

    @classmethod
    def name(cls):
      return 'isolated'

    def execute_codegen(self, targets):
      with self._task.context.new_workunit(name='execute', labels=[WorkUnitLabel.MULTITOOL]):
        ordered = [target for target in reversed(sort_targets(targets)) if target in targets]
        for target in ordered:
          with self._task.context.new_workunit(name=target.address.spec):
            # TODO(gm): add a test-case to ensure this is correctly eliminating stale generated code.
            safe_rmtree(self._task.codegen_workdir(target))
            self._do_execute_codegen([target])

    def find_sources(self, target):
      """Determines what sources were generated by the target after the fact.

      This is done by searching the directory where this target's code was generated. This is only
      possible because each target has its own unique directory in this CodegenStrategy.
      :param Target target: the target for which to find generated sources.
      :return: a set of relative filepaths.
      :rtype: OrderedSet
      """
      return self._find_sources_strictly_generated_by_target(target)

    def codegen_workdir_suffix(self, target):
      return os.path.join(self.name(), target.id)

    def _find_sources_generated_by_target(self, target):
      if target.id in self._generated_sources_cache:
        for source in self._generated_sources_cache[target.id]:
          yield source
        return
      target_workdir = self._task.codegen_workdir(target)
      if not os.path.exists(target_workdir):
        return
      for root, dirs, files in safe_walk(target_workdir):
        for name in files:
          yield os.path.join(root, name)

    def _find_sources_generated_by_dependencies(self, target):
      sources = OrderedSet()

      def add_sources(dep):
        if dep is not target:
          dep_sources = self._find_sources_generated_by_target(dep)
          dep_sources = [self._relative_source(dep, source) for source in dep_sources]
          sources.update(dep_sources)
      target.walk(add_sources)
      return sources

    def _relative_source(self, target, source):
      return os.path.relpath(source, self._task.codegen_workdir(target))

    def _find_sources_strictly_generated_by_target(self, target):
      # NB(gm): Some code generators may re-generate code that their dependent libraries generate.
      # This results in targets claiming to generate sources that they really don't, so we try to
      # filter out sources that were actually generated by dependencies of the target. This causes
      # the code generated by the dependencies to 'win' over the code generated by dependees. By
      # default, this behavior is disabled, and duplication in generated sources will raise a
      # TaskError. This is controlled by the --allow-dups flag.
      if target.id in self._generated_sources_cache:
        return self._generated_sources_cache[target.id]
      by_target = OrderedSet(self._find_sources_generated_by_target(target))
      by_dependencies = self._find_sources_generated_by_dependencies(target)
      strict = [t for t in by_target if self._relative_source(target, t) not in by_dependencies]
      if len(strict) != len(by_target):
        messages = ['{target} generated sources that had already been generated by dependencies.'
                    .format(target=target.address.spec)]
        # Doing some extra work for the sake of helpful error messages.
        duplicate_sources = set([self._relative_source(target, source)
                             for source in sorted(set(by_target) - set(strict))])
        duplicates_by_targets = {}

        def record_duplicates(dep):
          if dep == target:
            return
          sources = [self._relative_source(dep, s)
                     for s in self._find_sources_generated_by_target(dep)]
          sources = [s for s in sources if s in duplicate_sources]
          if sources:
            duplicates_by_targets[dep] = sources

        target.walk(record_duplicates)
        for dependency in sorted(duplicates_by_targets, key=lambda t: t.address.spec):
          messages.append('\t{} also generated:'.format(dependency.address.spec))
          messages.extend(['\t\t{}'.format(source) for source in duplicates_by_targets[dependency]])
        message = '\n'.join(messages)
        if self._task.get_options().allow_dups:
          logger.warn(message)
        else:
          raise self.DuplicateSourceError(message)

      self._generated_sources_cache[target.id] = strict
      return strict

    class DuplicateSourceError(TaskError):
      """A target generated the same code that was generated by one of its dependencies.

      This is only thrown when --allow-dups=False.
      """

  class UnsupportedStrategyError(TaskError):
    """Generated when there is no strategy for a given name."""
