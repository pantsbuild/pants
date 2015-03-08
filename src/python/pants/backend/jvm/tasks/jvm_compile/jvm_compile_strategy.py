# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from abc import ABCMeta, abstractmethod

from pants.util.dirutil import safe_mkdir
from pants.base.build_environment import get_buildroot, get_scm


class JvmCompileStrategy(object):
  """An abstract base strategy for JVM compilation."""

  __metaclass__ = ABCMeta

  def __init__(self, context, options, workdir, analysis_tools):
    self.context = context
    self._analysis_tools = analysis_tools

    self._target_sources_dir = os.path.join(workdir, 'target-sources')

    self._sources_by_target = None

  @abstractmethod
  def prepare_compile(self, cache_manager, sources_by_target, all_targets):
    """Prepares to compile the given set of targets.

    Has the side effects of pruning old analysis, and computing deleted sources.
    """
    pass

  @abstractmethod
  def invalidation_hints(self, sources_by_target):
    """A tuple of partition_size_hint and locally_changed targets for the given inputs."""
    pass

  @abstractmethod
  def compile_context(self, target):
    """Returns the default/stable compile context for the given target.
    
    Temporary compile contexts are private to the strategy.
    """
    pass

  @abstractmethod
  def compile_chunk(self,
                    invalidation_check,
                    sources_by_target,
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
  def compute_classes_by_source(self, compile_contexts):
    """Compute src->classes.

    Srcs are relative to buildroot. Classes are absolute paths.
    """
    pass

  @abstractmethod
  def compute_resource_mapping(self, compile_contexts):
    """Computes a merged ResourceMapping for the given compile contexts.
    
    Since classes should live in exactly one context, a merged mapping is unambiguous.
    """
    pass

  def pre_compile(self):
    # Only create these working dirs during execution phase, otherwise, they
    # would be wiped out by clean-all goal/task if it's specified.
    safe_mkdir(self._target_sources_dir)

  def class_name_for_class_file(self, compile_context, class_file_name):
    assert class_file_name.endswith(".class")
    assert class_file_name.startswith(compile_context.classes_dir)
    class_file_name = class_file_name[len(compile_context.classes_dir) + 1:-len(".class")]
    return class_file_name.replace("/", ".")

  def _validate_classpath(self, files):
    """Validates that all files are located within the working copy, to simplify relativization."""
    buildroot = get_buildroot()
    for _,f in files:
      if os.path.relpath(f, buildroot).startswith('..'):
        raise TaskError('Classpath entry {f} is located outside the buildroot.'.format(f=f))

  def _get_previous_sources_by_target(self, target):
    """Returns the target's sources as recorded on the last successful build of target.

    Returns a list of absolute paths.
    """
    path = os.path.join(self._target_sources_dir, target.identifier)
    if os.path.exists(path):
      with open(path, 'r') as infile:
        return [s.rstrip() for s in infile.readlines()]
    else:
      return []

  def _record_sources_by_target(self, target, sources):
    # Record target -> source mapping for future use.
    with open(os.path.join(self._target_sources_dir, target.identifier), 'w') as outfile:
      for src in sources:
        outfile.write(os.path.join(get_buildroot(), src))
        outfile.write('\n')

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

  # TODO: this is copy pasta between the strategy and jvm_compile.py
  def _sources_for_targets(self, targets):
    """Returns a map target->sources for the specified targets."""
    if self._sources_by_target is None:
      raise TaskError('self._sources_by_target not computed yet.')
    return dict((t, self._sources_by_target.get(t, [])) for t in targets)
