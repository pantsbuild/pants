# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import itertools
import logging
import os
from collections import OrderedDict, defaultdict

from twitter.common.collections import OrderedSet, maybe_list

from pants.backend.codegen.targets.java_protobuf_library import JavaProtobufLibrary
from pants.backend.codegen.targets.java_wire_library import JavaWireLibrary
from pants.backend.codegen.tasks.protobuf_gen import check_duplicate_conflicting_protos
from pants.backend.codegen.tasks.protobuf_parse import ProtobufParse
from pants.backend.codegen.tasks.simple_codegen_task import SimpleCodegenTask
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.backend.jvm.tasks.jvm_tool_task_mixin import JvmToolTaskMixin
from pants.base.address import SyntheticAddress
from pants.base.address_lookup_error import AddressLookupError
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.base.source_root import SourceRoot
from pants.java import util
from pants.option.options import Options


logger = logging.getLogger(__name__)


class WireGen(SimpleCodegenTask, JvmToolTaskMixin):
  @classmethod
  def register_options(cls, register):
    super(WireGen, cls).register_options(register)
    register('--javadeps', type=Options.list, default=['//:wire-runtime'],
             help='Runtime dependencies for wire-using Java code.')
    cls.register_jvm_tool(register, 'wire-compiler')

  def __init__(self, *args, **kwargs):
    """Generates Java files from .proto files using the Wire protobuf compiler."""
    super(WireGen, self).__init__(*args, **kwargs)
    self.java_out = os.path.join(self.workdir, 'gen-java')

  @property
  def synthetic_target_extra_dependencies(self):
    def resolve_deps(self, unresolved_deps):
      deps = OrderedSet()
      for dep in unresolved_deps:
        try:
          deps.update(self.context.resolve(dep))
        except AddressLookupError as e:
          raise self.DepLookupError('{message}\n  on dependency {dep}'.format(message=e, dep=dep))
      return deps
    return resolve_deps(self.get_options().javadeps)

  @property
  def synthetic_target_type(self):
    return JavaLibrary

  def sources_generated_by_target(self, target):
    def get_java_sources(path, source, service_writer):
      protobuf_parse = ProtobufParse(path, source)
      protobuf_parse.parse()

      types = protobuf_parse.messages | protobuf_parse.enums
      if service_writer:
        types |= protobuf_parse.services

      # Wire generates a single type for all of the 'extends' declarations in this file.
      if protobuf_parse.extends:
        types |= set(["Ext_{0}".format(protobuf_parse.filename)])

      java_files = list(self.calculate_java_genfiles(protobuf_parse.package, types))
      logger.debug('Path {path} yielded types {types} got files {java_files}'
                   .format(path=path, types=types, java_files=java_files))
      return java_files

    result = []
    for proto_source in sources:
      result.extend(get_java_sources(proto_source))
    return result

  def codegen_targets(self):
    return [target if isinstance(target, JavaWireLibrary) for target in self.context.targets()]
    for target in self.context.targets():
      if isinstance(target, JavaWireLibrary):
        yield target

  def is_proto_target(self, target):
    return isinstance(target, JavaProtobufLibrary)

  def genlangs(self):
    return {'java': lambda t: t.is_jvm}

  def genlang(self, lang, targets):
    # Invoke the generator once per target.  Because the wire compiler has flags that try to reduce
    # the amount of code emitted, Invoking them all together will break if one target specifies a
    # service_writer and another does not, or if one specifies roots and another does not.
    for target in targets:
      sources_by_base = self._calculate_sources([target])
      sources = OrderedSet(itertools.chain.from_iterable(sources_by_base.values()))
      relative_sources = OrderedSet()
      for source in sources:
        source_root = SourceRoot.find_by_path(source)
        if not source_root:
          source_root = SourceRoot.find(target)
        relative_source = os.path.relpath(source, source_root)
        relative_sources.add(relative_source)
      check_duplicate_conflicting_protos(self, sources_by_base, relative_sources, self.context.log)

      if lang != 'java':
        raise TaskError('Unrecognized wire gen lang: {0}'.format(lang))

      args = ['--java_out={0}'.format(self.java_out)]

      # Add all params in payload to args

      if target.payload.get_field_value('no_options'):
        args.append('--no_options')

      service_writer = target.payload.service_writer
      if service_writer:
        args.append('--service_writer={0}'.format(service_writer))

      registry_class = target.payload.registry_class
      if registry_class:
        args.append('--registry_class={0}'.format(registry_class))

      for root in target.payload.roots:
        args.append('--roots={0}'.format(root))

      for enum_option in target.payload.enum_options:
        args.append('--enum_options={0}'.format(enum_option))

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

  def createtarget(self, lang, gentarget, dependees):
    if lang == 'java':
      return self._create_java_target(gentarget, dependees)
    else:
      raise TaskError('Unrecognized wire gen lang: {0}'.format(lang))

  def _create_java_target(self, target, dependees):
    genfiles = []
    for source in target.sources_relative_to_source_root():
      path = os.path.join(target.target_base, source)
      genfiles.extend(self.calculate_genfiles(
        path,
        source,
        target.payload.service_writer).get('java', []))

    spec_path = os.path.relpath(self.java_out, get_buildroot())
    address = SyntheticAddress(spec_path, target.id)
    deps = OrderedSet(self.javadeps)
    tgt = self.context.add_new_target(address,
                                      JavaLibrary,
                                      derived_from=target,
                                      sources=genfiles,
                                      provides=target.provides,
                                      dependencies=deps,
                                      excludes=target.payload.excludes)
    for dependee in dependees:
      dependee.inject_dependency(tgt.address)
    return tgt


  def calculate_genfiles(self, path, source, service_writer):
    protobuf_parse = ProtobufParse(path, source)
    protobuf_parse.parse()

    types = protobuf_parse.messages | protobuf_parse.enums
    if service_writer:
      types |= protobuf_parse.services

    # Wire generates a single type for all of the 'extends' declarations in this file.
    if protobuf_parse.extends:
      types |= set(["Ext_{0}".format(protobuf_parse.filename)])

    genfiles = defaultdict(set)
    java_files = list(self.calculate_java_genfiles(protobuf_parse.package, types))
    logger.debug('Path {path} yielded types {types} got files {java_files}'
                 .format(path=path, types=types, java_files=java_files))
    genfiles['java'].update(java_files)
    return genfiles

  def calculate_java_genfiles(self, package, types):
    basepath = package.replace('.', '/')
    for type_ in types:
      filename = os.path.join(basepath, '{0}.java'.format(type_))
      logger.debug("Expecting {filename} from type {type_}".format(filename=filename, type_=type_))
      yield filename
