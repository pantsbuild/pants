# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import os

from twitter.common.collections import OrderedSet

from pants.backend.codegen.targets.java_wire_library import JavaWireLibrary
from pants.backend.codegen.tasks.simple_codegen_task import SimpleCodegenTask
from pants.backend.jvm.targets.jar_dependency import JarDependency
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.backend.jvm.tasks.jvm_tool_task_mixin import JvmToolTaskMixin
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.java.distribution.distribution import DistributionLocator


logger = logging.getLogger(__name__)


class WireGen(JvmToolTaskMixin, SimpleCodegenTask):

  @classmethod
  def register_options(cls, register):
    super(WireGen, cls).register_options(register)


    def wire_jar(name):
      return JarDependency(org='com.squareup.wire', name=name, rev='1.8.0')

    cls.register_jvm_tool(register,
                          'javadeps',
                          classpath=[
                            wire_jar(name='wire-runtime')
                          ],
                          classpath_spec='//:wire-runtime',
                          help='Runtime dependencies for wire-using Java code.')
    cls.register_jvm_tool(register, 'wire-compiler', classpath=[wire_jar(name='wire-compiler')])

  @classmethod
  def is_wire_compiler_jar(cls, jar):
    return 'com.squareup.wire' == jar.org and 'wire-compiler' == jar.name

  @classmethod
  def subsystem_dependencies(cls):
    return super(WireGen, cls).subsystem_dependencies() + (DistributionLocator,)

  def __init__(self, *args, **kwargs):
    """Generates Java files from .proto files using the Wire protobuf compiler."""
    super(WireGen, self).__init__(*args, **kwargs)

  def synthetic_target_type(self, target):
    return JavaLibrary

  def is_gentarget(self, target):
    return isinstance(target, JavaWireLibrary)

  def synthetic_target_extra_dependencies(self, target, target_workdir):
    wire_runtime_deps_spec = self.get_options().javadeps
    return self.resolve_deps([wire_runtime_deps_spec])

  def format_args_for_target(self, target, target_workdir):
    """Calculate the arguments to pass to the command line for a single target."""
    sources = OrderedSet(target.sources_relative_to_buildroot())

    relative_sources = OrderedSet()
    for source in sources:
      source_root = self.context.source_roots.find_by_path(source)
      if not source_root:
        source_root = self.context.source_roots.find(target)
      relative_source = os.path.relpath(source, source_root.path)
      relative_sources.add(relative_source)

    args = ['--java_out={0}'.format(target_workdir)]

    # Add all params in payload to args

    if target.payload.get_field_value('no_options'):
      args.append('--no_options')

    if target.payload.service_writer:
      args.append('--service_writer={}'.format(target.payload.service_writer))
      if target.payload.service_writer_options:
        for opt in target.payload.service_writer_options:
          args.append('--service_writer_opt')
          args.append(opt)

    registry_class = target.payload.registry_class
    if registry_class:
      args.append('--registry_class={0}'.format(registry_class))

    if target.payload.roots:
      args.append('--roots={0}'.format(','.join(target.payload.roots)))

    if target.payload.enum_options:
      args.append('--enum_options={0}'.format(','.join(target.payload.enum_options)))

    args.append('--proto_path={0}'.format(os.path.join(get_buildroot(),
        self.context.source_roots.find(target).path)))

    args.extend(relative_sources)
    return args

  def execute_codegen(self, target, target_workdir):
    execute_java = DistributionLocator.cached().execute_java
    args = self.format_args_for_target(target, target_workdir)
    if args:
      result = execute_java(classpath=self.tool_classpath('wire-compiler'),
                            main='com.squareup.wire.WireCompiler',
                            args=args)
      if result != 0:
        raise TaskError('Wire compiler exited non-zero ({0})'.format(result))

  class WireCompilerVersionError(TaskError):
    """Indicates the wire compiler version could not be determined."""

  def _calculate_proto_paths(self, target):
    """Computes the set of paths that wire uses to lookup imported protos.

    The protos under these paths are not compiled, but they are required to compile the protos that
    imported.
    :param target: the JavaWireLibrary target to compile.
    :return: an ordered set of directories to pass along to wire.
    """
    proto_paths = OrderedSet()
    proto_paths.add(os.path.join(get_buildroot(), self.context.source_roots.find(target).path))

    def collect_proto_paths(dep):
      if not dep.has_sources():
        return
      for source in dep.sources_relative_to_buildroot():
        if source.endswith('.proto'):
          root = self.context.source_roots.find_by_path(source)
          if root:
            proto_paths.add(os.path.join(get_buildroot(), root.path))

    collect_proto_paths(target)
    target.walk(collect_proto_paths)
    return proto_paths
