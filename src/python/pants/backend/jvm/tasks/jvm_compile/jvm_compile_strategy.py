# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from abc import ABCMeta, abstractmethod
from collections import defaultdict, namedtuple

from twitter.common.collections import OrderedSet

from pants.base.build_environment import get_buildroot, get_scm
from pants.base.exceptions import TaskError
from pants.util.dirutil import safe_delete, safe_mkdir


class JvmCompileStrategy(object):
  """An abstract base strategy for JVM compilation."""

  __metaclass__ = ABCMeta

  class CompileContext(object):
    """A context for the compilation of a target.
    
    This can be used to differentiate between a partially completed compile in a temporary location
    and a finalized compile in its permanent location.
    """
    def __init__(self, target, analysis_file, classes_dir, sources):
      self.target = target
      self.analysis_file = analysis_file
      self.classes_dir = classes_dir
      self.sources = sources

    @property
    def _id(self):
      return (self.target, self.analysis_file, self.classes_dir)

    def __eq__(self, other):
      return self._id == other._id

    def __hash__(self):
      return hash(self._id)

  # Common code.
  # ------------
  @staticmethod
  def _analysis_for_target(analysis_dir, target):
    return os.path.join(analysis_dir, target.id + '.analysis')

  @staticmethod
  def _portable_analysis_for_target(analysis_dir, target):
    return JvmCompileStrategy._analysis_for_target(analysis_dir, target) + '.portable'

  @classmethod
  @abstractmethod
  def register_options(cls, register, language):
    """Registration for strategy-specific options.

    The abstract base class does not register any options itself: those are left to JvmCompile.
    """
    pass

  def __init__(self, context, options, workdir, analysis_tools, sources_predicate):
    self.context = context
    self._analysis_tools = analysis_tools

    # Mapping of relevant (as selected by the predicate) sources by target.
    self._sources_by_target = None
    self._sources_predicate = sources_predicate

    # The ivy confs for which we're building.
    self._confs = options.confs
    self._clear_invalid_analysis = options.clear_invalid_analysis

  @abstractmethod
  def name(self):
    """A readable, unique name for this strategy."""
    pass

  @abstractmethod
  def invalidation_hints(self, relevant_targets):
    """A tuple of partition_size_hint and locally_changed targets for the given inputs."""
    pass

  @abstractmethod
  def compile_context(self, target):
    """Returns the default/stable compile context for the given target.

    Temporary compile contexts are private to the strategy.
    """
    pass

  @abstractmethod
  def compute_classes_by_source(self, compile_contexts):
    """Compute a map of (context->(src->classes)) for the given compile_contexts.

    It's possible (although unfortunate) for multiple targets to own the same sources, hence
    the top level division. Srcs are relative to buildroot. Classes are absolute paths.
    """
    pass

  @abstractmethod
  def compile_chunk(self,
                    invalidation_check,
                    all_targets,
                    relevant_targets,
                    invalid_targets,
                    extra_compile_time_classpath_elements,
                    compile_vts,
                    register_vts,
                    update_artifact_cache_vts_work):
    """Executes compilations for that invalid targets contained in a single language chunk."""
    pass

  @abstractmethod
  def post_process_cached_vts(self, cached_vts):
    """Post processes VTS that have been fetched from the cache."""
    pass

  @abstractmethod
  def compute_resource_mapping(self, compile_contexts):
    """Computes a merged ResourceMapping for the given compile contexts.

    Since classes should live in exactly one context, a merged mapping is unambiguous.
    """
    pass

  def pre_compile(self):
    """Executed once before any compiles."""
    pass

  def validate_analysis(self, path):
    """Throws a TaskError for invalid analysis files."""
    try:
      self._analysis_parser.validate_analysis(path)
    except Exception as e:
      if self._clear_invalid_analysis:
        self.context.log.warn("Invalid analysis detected at path {} ... pants will remove these "
                              "automatically, but\nyou may experience spurious warnings until "
                              "clean-all is executed.\n{}".format(path, e))
        safe_delete(path)
      else:
        raise TaskError("An internal build directory contains invalid/mismatched analysis: please "
                        "run `clean-all` if your tools versions changed recently:\n{}".format(e))

  def prepare_compile(self, cache_manager, all_targets, relevant_targets):
    """Prepares to compile the given set of targets.

    Has the side effects of pruning old analysis, and computing deleted sources.
    """
    # Target -> sources (relative to buildroot).
    # TODO(benjy): Should sources_by_target be available in all Tasks?
    self._sources_by_target = self._compute_sources_by_target(relevant_targets)

  def class_name_for_class_file(self, compile_context, class_file_name):
    assert class_file_name.endswith(".class")
    assert class_file_name.startswith(compile_context.classes_dir)
    class_file_name = class_file_name[len(compile_context.classes_dir) + 1:-len(".class")]
    return class_file_name.replace("/", ".")

  def _compute_sources_by_target(self, targets):
    """Computes and returns a map target->sources (relative to buildroot)."""
    def resolve_target_sources(target_sources):
      resolved_sources = []
      for target in target_sources:
        if target.has_sources():
          resolved_sources.extend(target.sources_relative_to_buildroot())
      return resolved_sources
    def calculate_sources(target):
      sources = [s for s in target.sources_relative_to_buildroot() if self._sources_predicate(s)]
      # TODO: Make this less hacky. Ideally target.java_sources will point to sources, not targets.
      if hasattr(target, 'java_sources') and target.java_sources:
        sources.extend(resolve_target_sources(target.java_sources))
      return sources
    return {t: calculate_sources(t) for t in targets}

  def _sources_for_targets(self, targets):
    """Returns a cached map of target->sources for the specified targets."""
    if self._sources_by_target is None:
      raise TaskError('self._sources_by_target not computed yet.')
    return {t: self._sources_by_target.get(t, []) for t in targets}

  def _sources_for_target(self, target):
    """Returns the cached sources for the given target."""
    if self._sources_by_target is None:
      raise TaskError('self._sources_by_target not computed yet.')
    return self._sources_by_target.get(target, [])

  def _validate_classpath(self, classpath):
    """Validates that all files are located within the working copy, to simplify relativization."""
    buildroot = get_buildroot()
    for _, f in classpath:
      if os.path.relpath(f, buildroot).startswith('..'):
        raise TaskError('Classpath entry {f} is located outside the buildroot.'.format(f=f))

  def _find_locally_changed_targets(self, sources_by_target):
    """Finds the targets whose sources have been modified locally.

    Returns a list of targets, or None if no SCM is available.
    """
    # Compute the src->targets mapping. There should only be one target per source,
    # but that's not yet a hard requirement, so the value is a list of targets.
    # TODO(benjy): Might this inverse mapping be needed elsewhere too?
    targets_by_source = defaultdict(list)
    for tgt, srcs in sources_by_target.items():
      for src in srcs:
        targets_by_source[src].append(tgt)

    ret = OrderedSet()
    scm = get_scm()
    if not scm:
      return None
    changed_files = scm.changed_files(include_untracked=True, relative_to=get_buildroot())
    for f in changed_files:
      ret.update(targets_by_source.get(f, []))
    return list(ret)

  @property
  def _analysis_parser(self):
    return self._analysis_tools.parser
