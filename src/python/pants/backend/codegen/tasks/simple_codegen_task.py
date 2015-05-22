# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.core.tasks.task import Task
from pants.base.address import SyntheticAddress
from pants.base.build_environment import get_buildroot
from pants.base.source_root import SourceRoot


class SimpleCodegenTask(Task):
  """Simpler base-class for single-language code-gen.

  Subclasses should implement at minimum: synthetic_target_type, is_gentarget, execute_codegen, and
  sources_generated_by_target.
  """

  @classmethod
  def get_fingerprint_strategy(cls):
    """Override this method to use a fingerprint strategy other than the default one.

    :return: a fingerprint strategy, or None to use the default strategy.
    """
    return None

  def synthetic_target_extra_dependencies(self, target):
    """Gets any extra dependencies generated synthetic targets should have. This method is optional
    for subclasses to implement, because some code generators may have no extra dependencies.

    :param target: the Target from which we are generating a synthetic Target. E.g., 'target' might
    be a JavaProtobufLibrary, whose corresponding synthetic Target would be a JavaLibrary. It is not
    necessary to use this parameter; it may be unnecessary depending on the details of the subclass.
    :return: a list of dependencies.
    """
    return []

  @property
  def synthetic_target_type(self):
    """The type of target this codegen task generates. For example, the target type for JaxbGen
    would simply be JavaLibrary.

    :return: a type (class) that inherits from Target.
    """
    raise NotImplementedError

  def is_gentarget(self, target):
    """Predicate which determines whether the target in question is relevant to this codegen task.
    E.g., the JaxbGen task considers JaxbLibrary targets to be relevant, and nothing else.

    :param target: The target to check.
    :return: True if this class can generate code for the given target, False otherwise.
    """
    raise NotImplementedError

  def execute_codegen(self, invalid_targets):
    """Generated code for the given list of targets.

    :param invalid_targets: an iterable of targets (a subset of codegen_targets()).
    """
    raise NotImplementedError

  def sources_generated_by_target(self, target):
    """Predicts what source files will be generated from the given codegen target.

    :param target: the codegen target in question (eg a .proto library).
    :return: an iterable of strings containing the file system paths to the sources files.
    """
    raise NotImplementedError

  def codegen_targets(self):
    """Finds codegen targets in the depencency graph.

    :return: an iterable of dependency targets.
    """
    return self.context.targets(self.is_gentarget)

  def codegen_workdir(self, target):
    """The path to the directory code should be generated in. E.g., this might be something like
    /home/user/repo/.pants.d/gen/jaxb/...

    :return: The absolute file path.
    """
    # TODO(gm): This method will power the isolated/global strategies for what directories to put
    # generated code in, once that exists. This will work in a similar fashion to the jvm_compile
    # tasks' isolated vs global strategies, generated code per-target in a way that avoids
    # collisions.
    return self.workdir

  def execute(self):
    targets = self.codegen_targets()
    with self.invalidated(targets,
                          invalidate_dependents=True,
                          fingerprint_strategy=self.get_fingerprint_strategy()) as invalidation_check:
      for vts in invalidation_check.invalid_vts_partitioned:
        invalid_targets = vts.targets
        self.execute_codegen(invalid_targets)

      invalid_vts_by_target = dict([(vt.target, vt) for vt in invalidation_check.invalid_vts])
      vts_artifactfiles_pairs = []

      for target in targets:
        target_workdir = self.codegen_workdir(target)
        synthetic_name = target.id
        sources_rel_path = os.path.relpath(target_workdir, get_buildroot())
        spec_path = '{0}{1}'.format(type(self).__name__, sources_rel_path)
        synthetic_address = SyntheticAddress(spec_path, synthetic_name)
        raw_generated_sources = self.sources_generated_by_target(target)
        # Make the sources robust regardless of whether subclasses return relative paths, or
        # absolute paths that are subclasses of the workdir.
        generated_sources = [src if src.startswith(target_workdir)
                             else os.path.join(target_workdir, src)
                             for src in raw_generated_sources]
        relative_generated_sources = [os.path.relpath(src, target_workdir)
                                      for src in generated_sources]

        self.target = self.context.add_new_target(
          address=synthetic_address,
          target_type=self.synthetic_target_type,
          dependencies=self.synthetic_target_extra_dependencies(target),
          sources_rel_path=sources_rel_path,
          sources=relative_generated_sources,
          derived_from=target,
          provides=target.provides,
        )
        synthetic_target = self.target

        build_graph = self.context.build_graph

        # NOTE(pl): This bypasses the convenience function (Target.inject_dependency) in order
        # to improve performance.  Note that we can walk the transitive dependee subgraph once
        # for transitive invalidation rather than walking a smaller subgraph for every single
        # dependency injected.
        for dependent_address in build_graph.dependents_of(target.address):
          build_graph.inject_dependency(
            dependent=dependent_address,
            dependency=synthetic_target.address,
          )
        # NOTE(pl): See the above comment.  The same note applies.
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
