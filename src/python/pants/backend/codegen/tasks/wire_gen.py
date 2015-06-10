# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import itertools
import logging
import os
from collections import OrderedDict

from twitter.common.collections import OrderedSet

from pants.backend.codegen.targets.java_wire_library import JavaWireLibrary
from pants.backend.codegen.tasks.protobuf_gen import check_duplicate_conflicting_protos
from pants.backend.codegen.tasks.protobuf_parse import ProtobufParse
from pants.backend.codegen.tasks.simple_codegen_task import SimpleCodegenTask
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.backend.jvm.tasks.jvm_tool_task_mixin import JvmToolTaskMixin
from pants.base.address_lookup_error import AddressLookupError
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.base.source_root import SourceRoot
from pants.java import util
from pants.option.options import Options


logger = logging.getLogger(__name__)


class WireGen(JvmToolTaskMixin, SimpleCodegenTask):
  @classmethod
  def register_options(cls, register):
    super(WireGen, cls).register_options(register)
    register('--javadeps', type=Options.list, default=['//:wire-runtime'],
             help='Runtime dependencies for wire-using Java code.')
    cls.register_jvm_tool(register, 'wire-compiler')

  def __init__(self, *args, **kwargs):
    """Generates Java files from .proto files using the Wire protobuf compiler."""
    super(WireGen, self).__init__(*args, **kwargs)

  @property
  def synthetic_target_type(self):
    return JavaLibrary

  def is_gentarget(self, target):
    return isinstance(target, JavaWireLibrary)

  @classmethod
  def supported_strategy_types(cls):
    return [cls.IsolatedCodegenStrategy,]

  def sources_generated_by_target(self, target):
    genfiles = []
    for source in target.sources_relative_to_source_root():
      path = os.path.join(target.target_base, source)
      genfiles.extend(self.calculate_genfiles(
        path,
        source,
        target.payload.service_writer))
    return genfiles

  def resolve_deps(self, unresolved_deps):
    deps = OrderedSet()
    for dep in unresolved_deps:
      try:
        deps.update(self.context.resolve(dep))
      except AddressLookupError as e:
        raise self.DepLookupError('{message}\n  on dependency {dep}'.format(message=e, dep=dep))
    return deps

  def synthetic_target_extra_dependencies(self, target):
    return self.resolve_deps(self.get_options().javadeps)

  def execute_codegen(self, targets):
    # Invoke the generator once per target.  Because the wire compiler has flags that try to reduce
    # the amount of code emitted, Invoking them all together will break if one target specifies a
    # service_writer and another does not, or if one specifies roots and another does not.
    for target in targets:
      sources_by_base = self._calculate_sources([target])
      if self.codegen_strategy.name() == 'isolated':
        sources = OrderedSet(target.sources_relative_to_buildroot())
      else:
        sources = OrderedSet(itertools.chain.from_iterable(sources_by_base.values()))
      if not self.validate_sources_present(sources, [target]):
        continue
      relative_sources = OrderedSet()
      for source in sources:
        source_root = SourceRoot.find_by_path(source)
        if not source_root:
          source_root = SourceRoot.find(target)
        relative_source = os.path.relpath(source, source_root)
        relative_sources.add(relative_source)
      check_duplicate_conflicting_protos(self, sources_by_base, relative_sources, self.context.log)

      args = ['--java_out={0}'.format(self.codegen_workdir(target))]

      # Add all params in payload to args

      if target.payload.get_field_value('no_options'):
        args.append('--no_options')

      service_writer = target.payload.service_writer
      if service_writer:
        args.append('--service_writer={0}'.format(service_writer))

      registry_class = target.payload.registry_class
      if registry_class:
        args.append('--registry_class={0}'.format(registry_class))

      if target.payload.roots:
        args.append('--roots={0}'.format(','.join(target.payload.roots)))

      if target.payload.enum_options:
        args.append('--enum_options={0}'.format(','.join(target.payload.enum_options)))

      args.append('--proto_path={0}'.format(os.path.join(get_buildroot(),
                                                         SourceRoot.find(target))))

      args.extend(relative_sources)

      result = util.execute_java(classpath=self.tool_classpath('wire-compiler'),
                                 main='com.squareup.wire.WireCompiler',
                                 args=args)
      if result != 0:
        raise TaskError('Wire compiler exited non-zero ({0})'.format(result))

  def _calculate_sources(self, targets):
    def add_to_gentargets(target):
      if self.is_gentarget(target):
        gentargets.add(target)
    gentargets = OrderedSet()
    self.context.build_graph.walk_transitive_dependency_graph(
      [target.address for target in targets],
      add_to_gentargets,
      postorder=True)
    sources_by_base = OrderedDict()
    for target in gentargets:
      base, sources = target.target_base, target.sources_relative_to_buildroot()
      if base not in sources_by_base:
        sources_by_base[base] = OrderedSet()
      sources_by_base[base].update(sources)
    return sources_by_base

  def calculate_genfiles(self, path, source, service_writer):
    protobuf_parse = ProtobufParse(path, source)
    protobuf_parse.parse()

    types = protobuf_parse.messages | protobuf_parse.enums
    if service_writer:
      types |= protobuf_parse.services

    # Wire generates a single type for all of the 'extends' declarations in this file.
    if protobuf_parse.extends:
      types |= set(["Ext_{0}".format(protobuf_parse.filename)])

    java_files = self.calculate_java_genfiles(protobuf_parse.package, types)
    logger.debug('Path {path} yielded types {types} got files {java_files}'
                 .format(path=path, types=types, java_files=java_files))
    return set(java_files)

  def calculate_java_genfiles(self, package, types):
    basepath = package.replace('.', '/')
    return [os.path.join(basepath, '{0}.java'.format(t)) for t in types]
