# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from collections import defaultdict
import os

from twitter.common.collections import OrderedDict, OrderedSet, maybe_list

from pants.backend.codegen.targets.java_wire_library import JavaWireLibrary
from pants.backend.codegen.tasks.code_gen import CodeGen
from pants.backend.codegen.tasks.protobuf_gen import check_duplicate_conflicting_protos
from pants.backend.codegen.tasks.protobuf_parse import ProtobufParse
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.backend.jvm.tasks.jvm_tool_task_mixin import JvmToolTaskMixin
from pants.base.address import SyntheticAddress
from pants.base.address_lookup_error import AddressLookupError
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.util.dirutil import safe_mkdir
from pants.java import util


class WireGen(CodeGen, JvmToolTaskMixin):
  def __init__(self, *args, **kwargs):
    super(WireGen, self).__init__(*args, **kwargs)

    self.wire_version = self.context.config.get('wire-gen', 'version',
                                                default='1.5.2')

    self.java_out = os.path.join(self.workdir, 'gen-java')

    self.proto_path = get_buildroot()

    self.register_jvm_tool_from_config(key='wire',
                                       config=self.context.config,
                                       ini_section='wire-gen',
                                       ini_key='bootstrap-tools',
                                       default=['//:wire-compiler'])

  def resolve_deps(self, key, default=[]):
    deps = OrderedSet()
    for dep in self.context.config.getlist('wire-gen', key, default=maybe_list(default)):
      if dep:
        try:
          deps.update(self.context.resolve(dep))
        except AddressLookupError as e:
          raise self.DepLookupError("{message}\n  referenced from [{section}] key: {key} in pants.ini"
                                    .format(message=e, section='wire-gen', key=key))
    return deps

  @property
  def javadeps(self):
    return self.resolve_deps('javadeps',
                             default='//:wire-runtime'
                             .format(version=self.wire_version))

  def is_gentarget(self, target):
    return isinstance(target, JavaWireLibrary)

  def genlangs(self):
    return {'java': lambda t: t.is_jvm}

  def _same_contents(self, a, b):
    with open(a, 'r') as f:
      a_data = f.read()
    with open(b, 'r') as f:
      b_data = f.read()
    return a_data == b_data

  def genlang(self, lang, targets):
    sources_by_base = self._calculate_sources(targets)
    sources = reduce(lambda a, b: a ^ b, sources_by_base.values(), OrderedSet())

    check_duplicate_conflicting_protos(sources_by_base, sources, self.context)

    if lang != 'java':
      raise TaskError('Unrecognized wire gen lang: %s' % lang)

    output_dir = self.java_out
    gen_flag = '--java_out'
    safe_mkdir(output_dir)
    gen = '%s=%s' % (gen_flag, output_dir)
    args = [gen]
    args.append('--proto_path=%s' % self.proto_path)
    args.extend(sources)

    util.execute_java(classpath=self.tool_classpath('wire'),
                      main='com.squareup.wire.WireCompiler',
                      args=args)

  def _calculate_sources(self, targets):
    walked_targets = set()
    for target in targets:
      walked_targets.update(t for t in target.closure() if self.is_gentarget(t))

    sources_by_base = OrderedDict()
    for target in self.context.build_graph.targets():
      if target in walked_targets:
        base, sources = target.target_base, target.sources_relative_to_buildroot()
        if base not in sources_by_base:
          sources_by_base[base] = OrderedSet()
        sources_by_base[base].update(sources)
    return sources_by_base

  def createtarget(self, lang, gentarget, dependees):
    if lang == 'java':
      return self._create_java_target(gentarget, dependees)
    else:
      raise TaskError('Unrecognized wire gen lang: %s' % lang)

  def _create_java_target(self, target, dependees):
    genfiles = []
    for source in target.sources_relative_to_source_root():
      path = os.path.join(target.target_base, source)
      genfiles.extend(calculate_genfiles(path, source).get('java', []))

    spec_path = os.path.relpath(self.java_out, get_buildroot())
    address = SyntheticAddress(spec_path, target.id)
    deps = OrderedSet(self.javadeps)
    jars_tgt = self.context.add_new_target(SyntheticAddress(spec_path, target.id + str('-rjars')),
                                           JarLibrary,
                                           # jars=import_jars,
                                           derived_from=target)
    # Add in the 'spec-rjars' target, which contains all the JarDependency targets passed in via the
    # imports parameter. Each of these jars is expected to contain .proto files bundled together
    # with their .class files.
    deps.add(jars_tgt)
    tgt = self.context.add_new_target(address,
                                      JavaLibrary,
                                      derived_from=target,
                                      sources=genfiles,
                                      provides=target.provides,
                                      dependencies=deps,
                                      excludes=target.payload.get_field_value('excludes'))
    for dependee in dependees:
      dependee.inject_dependency(tgt.address)
    return tgt


def calculate_genfiles(path, source):
  protobuf_parse = ProtobufParse('wire', path, source)
  protobuf_parse.parse()

  genfiles = defaultdict(set)
  genfiles['java'].update(calculate_java_genfiles(protobuf_parse.package, protobuf_parse.types))
  return genfiles

def calculate_java_genfiles(package, types):
  basepath = package.replace('.', '/')

  def path(name):
    return os.path.join(basepath, '%s.java' % name)

  for type_ in types:
    yield path(type_)
