# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import re
from collections import defaultdict

from pants.backend.jvm.targets.jar_dependency import JarDependency
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.backend.jvm.targets.scala_library import ScalaLibrary
from pants.backend.jvm.tasks.nailgun_task import NailgunTask
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.build_graph.address import Address
from twitter.common.dirutil import safe_mkdir

from pants.contrib.spindle.targets.spindle_thrift_library import SpindleThriftLibrary


class SpindleGen(NailgunTask):
  @classmethod
  def product_types(cls):
    return [
      'scala',
    ]

  @classmethod
  def register_options(cls, register):
    super(SpindleGen, cls).register_options(register)
    register(
      '--runtime-dependency',
      default=['3rdparty:spindle-runtime'],
      advanced=True,
      type=list,
      help='A list of targets that all spindle codegen depends on at runtime.',
    )
    cls.register_jvm_tool(register,
                          'spindle-codegen',
                          classpath=[
                            JarDependency(org='com.foursquare',
                                          name='spindle-codegen-binary_2.10',
                                          rev='3.0.0-M7'),
                          ])

  @property
  def spindle_classpath(self):
    return self.tool_classpath('spindle-codegen')

  @property
  def synthetic_target_extra_dependencies(self):
    return set(
      dep_target
      for dep_spec in self.get_options().runtime_dependency
      for dep_target in self.context.resolve(dep_spec)
    )

  @property
  def namespace_out(self):
    return os.path.join(self.workdir, 'src', 'jvm')

  def codegen_targets(self):
    return self.context.targets(lambda t: isinstance(t, SpindleThriftLibrary))

  def sources_generated_by_target(self, target):
    return [
      os.path.join(self.namespace_out, relative_genned_source)
      for thrift_source in target.sources_relative_to_buildroot()
      for relative_genned_source in calculate_genfiles(thrift_source)
    ]

  def execute_codegen(self, targets):
    sources = self._calculate_sources(targets, lambda t: isinstance(t, SpindleThriftLibrary))
    bases = set(
      target.target_base
      for target in self.context.targets(lambda t: isinstance(t, SpindleThriftLibrary))
    )
    scalate_workdir = os.path.join(self.workdir, 'scalate_workdir')
    safe_mkdir(self.namespace_out)
    safe_mkdir(scalate_workdir)

    args = [
      '--template', 'scala/record.ssp',
      '--java_template', 'javagen/record.ssp',
      '--thrift_include', ':'.join(bases),
      '--namespace_out', self.namespace_out,
      '--working_dir', scalate_workdir,
    ]
    args.extend(sources)

    result = self.runjava(classpath=self.spindle_classpath,
                          main='com.foursquare.spindle.codegen.binary.ThriftCodegen',
                          jvm_options=self.get_options().jvm_options,
                          args=args,
                          workunit_name='generate')
    if result != 0:
      raise TaskError('{} returned {}'.format(self.main_class, result))

  def execute(self):
    targets = self.codegen_targets()
    build_graph = self.context.build_graph
    with self.invalidated(targets, invalidate_dependents=True) as invalidation_check:
      for vts in invalidation_check.invalid_vts:
        invalid_targets = vts.targets
        self.execute_codegen(invalid_targets)

      invalid_vts_by_target = dict([(vt.target, vt) for vt in invalidation_check.invalid_vts])
      vts_artifactfiles_pairs = defaultdict(list)

      for target in targets:
        java_synthetic_name = '{0}-{1}'.format(target.id, 'java')
        java_sources_rel_path = os.path.relpath(self.namespace_out, get_buildroot())
        java_synthetic_address = Address(java_sources_rel_path, java_synthetic_name)
        java_generated_sources = [
          os.path.join(os.path.dirname(source), 'java_{0}.java'.format(os.path.basename(source)))
          for source in self.sources_generated_by_target(target)
        ]
        java_relative_generated_sources = [os.path.relpath(src, self.namespace_out)
                                           for src in java_generated_sources]

        # We can't use context.add_new_target because it now does fancy management
        # of synthetic target / target root interaction that breaks us here.
        java_target_base = os.path.join(get_buildroot(), java_synthetic_address.spec_path)
        if not os.path.exists(java_target_base):
          os.makedirs(java_target_base)
        build_graph.inject_synthetic_target(
          address=java_synthetic_address,
          target_type=JavaLibrary,
          dependencies=[dep.address for dep in self.synthetic_target_extra_dependencies],
          derived_from=target,
          sources=java_relative_generated_sources,
        )
        java_synthetic_target = build_graph.get_target(java_synthetic_address)

        # NOTE(pl): This bypasses the convenience function (Target.inject_dependency) in order
        # to improve performance.  Note that we can walk the transitive dependee subgraph once
        # for transitive invalidation rather than walking a smaller subgraph for every single
        # dependency injected.  This walk is done below, after the scala synthetic target is
        # injected.
        for concrete_dependency_address in build_graph.dependencies_of(target.address):
          build_graph.inject_dependency(
            dependent=java_synthetic_target.address,
            dependency=concrete_dependency_address,
          )

        if target in invalid_vts_by_target:
          vts_artifactfiles_pairs[invalid_vts_by_target[target]].extend(java_generated_sources)

        synthetic_name = '{0}-{1}'.format(target.id, 'scala')
        sources_rel_path = os.path.relpath(self.namespace_out, get_buildroot())
        synthetic_address = Address(sources_rel_path, synthetic_name)
        generated_sources = [
          '{0}.{1}'.format(source, 'scala')
          for source in self.sources_generated_by_target(target)
        ]
        relative_generated_sources = [os.path.relpath(src, self.namespace_out)
                                      for src in generated_sources]
        synthetic_target = self.context.add_new_target(
          address=synthetic_address,
          target_type=ScalaLibrary,
          dependencies=self.synthetic_target_extra_dependencies,
          sources=relative_generated_sources,
          derived_from=target,
          java_sources=[java_synthetic_target.address.spec],
        )

        # NOTE(pl): This bypasses the convenience function (Target.inject_dependency) in order
        # to improve performance.  Note that we can walk the transitive dependee subgraph once
        # for transitive invalidation rather than walking a smaller subgraph for every single
        # dependency injected.  This walk also covers the invalidation for the java synthetic
        # target above.
        for dependent_address in build_graph.dependents_of(target.address):
          build_graph.inject_dependency(dependent=dependent_address,
                                        dependency=synthetic_target.address)
        # NOTE(pl): See the above comment.  The same note applies.
        for concrete_dependency_address in build_graph.dependencies_of(target.address):
          build_graph.inject_dependency(
            dependent=synthetic_target.address,
            dependency=concrete_dependency_address,
          )
        build_graph.walk_transitive_dependee_graph(
          [target.address],
          work=lambda t: t.mark_transitive_invalidation_hash_dirty(),
        )

        if target in self.context.target_roots:
          self.context.target_roots.append(synthetic_target)
        if target in invalid_vts_by_target:
          vts_artifactfiles_pairs[invalid_vts_by_target[target]].extend(generated_sources)

      if self.artifact_cache_writes_enabled():
        self.update_artifact_cache(vts_artifactfiles_pairs.items())

  def _calculate_sources(self, thrift_targets, target_filter):
    sources = set()
    def collect_sources(target):
      if target_filter(target):
        sources.update(target.sources_relative_to_buildroot())
    for target in thrift_targets:
      target.walk(collect_sources)
    return sources

# Slightly hacky way to figure out which files get generated from a particular thrift source.
# TODO(benjy): This could be emitted by the codegen tool.
# That would also allow us to easily support 1:many codegen.
NAMESPACE_PARSER = re.compile(r'^\s*namespace\s+([^\s]+)\s+([^\s]+)\s*$')


def calculate_genfiles(source):
  abs_source = os.path.join(get_buildroot(), source)
  with open(abs_source, 'r') as thrift:
    lines = thrift.readlines()
  namespaces = {}
  for line in lines:
    match = NAMESPACE_PARSER.match(line)
    if match:
      lang = match.group(1)
      namespace = match.group(2)
      namespaces[lang] = namespace

  namespace = namespaces.get('java')

  if not namespace:
    raise TaskError('No namespace provided in source: {}'.format(abs_source))

  return calculate_scala_record_genfiles(namespace, abs_source)


def calculate_scala_record_genfiles(namespace, source):
  """Returns the generated file basenames, add .java or .scala to get the full path."""
  basepath = namespace.replace('.', '/')
  name = os.path.splitext(os.path.basename(source))[0]
  return [os.path.join(basepath, name)]
