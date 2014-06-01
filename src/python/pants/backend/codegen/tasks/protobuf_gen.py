# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from collections import defaultdict
import os
import re
import subprocess

from twitter.common import log
from twitter.common.collections import OrderedSet
from twitter.common.dirutil import safe_mkdir

from pants.backend.codegen.targets.java_protobuf_library import JavaProtobufLibrary
from pants.backend.codegen.tasks.code_gen import CodeGen
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.backend.python.targets.python_library import PythonLibrary
from pants.base.address import SyntheticAddress
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.binary_util import select_binary


class ProtobufGen(CodeGen):
  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    option_group.add_option(mkflag('lang'), dest='protobuf_gen_langs', default=[],
                            action='append', type='choice', choices=['python', 'java'],
                            help='Force generation of protobuf code for these languages.')

  def __init__(self, context, workdir):
    super(ProtobufGen, self).__init__(context, workdir)

    self.protoc_supportdir = self.context.config.get('protobuf-gen', 'supportdir')
    self.protoc_version = self.context.config.get('protobuf-gen', 'version')
    self.plugins = self.context.config.getlist('protobuf-gen', 'plugins', default=[])

    self.java_out = os.path.join(self.workdir, 'gen-java')
    self.py_out = os.path.join(self.workdir, 'gen-py')

    self.gen_langs = set(context.options.protobuf_gen_langs)
    for lang in ('java', 'python'):
      if self.context.products.isrequired(lang):
        self.gen_langs.add(lang)

    self.protobuf_binary = select_binary(
      self.protoc_supportdir,
      self.protoc_version,
      'protoc',
      context.config
    )

  def resolve_deps(self, key):
    deps = OrderedSet()
    for dep in self.context.config.getlist('protobuf-gen', key):
      deps.update(self.context.resolve(dep))
    return deps

  @property
  def javadeps(self):
    return self.resolve_deps('javadeps')

  @property
  def pythondeps(self):
    return self.resolve_deps('pythondeps')

  def invalidate_for(self):
    return self.gen_langs

  def invalidate_for_files(self):
    return [self.protobuf_binary]

  def is_gentarget(self, target):
    return isinstance(target, JavaProtobufLibrary)

  def is_forced(self, lang):
    return lang in self.gen_langs

  def genlangs(self):
    return dict(java=lambda t: t.is_jvm, python=lambda t: t.is_python)

  def genlang(self, lang, targets):
    bases, sources = self._calculate_sources(targets)

    if lang == 'java':
      output_dir = self.java_out
      gen_flag = '--java_out'
    elif lang == 'python':
      output_dir = self.py_out
      gen_flag = '--python_out'
    else:
      raise TaskError('Unrecognized protobuf gen lang: %s' % lang)

    safe_mkdir(output_dir)
    gen = '%s=%s' % (gen_flag, output_dir)

    args = [self.protobuf_binary, gen]

    if self.plugins:
      for plugin in self.plugins:
        # TODO(Eric Ayers) Is it a good assumption that the generated source output dir is
        # acceptable for all plugins?
        args.append("--%s_protobuf_out=%s" % (plugin, output_dir))

    for base in bases:
      args.append('--proto_path=%s' % base)

    args.extend(sources)
    log.debug('Executing: %s' % ' '.join(args))
    process = subprocess.Popen(args)
    result = process.wait()
    if result != 0:
      raise TaskError('%s ... exited non-zero (%i)' % (self.protobuf_binary, result))

  def _calculate_sources(self, targets):
    bases = set()
    sources = set()

    def collect_sources(target):
      if self.is_gentarget(target):
        bases.add(target.target_base)
        sources.update(target.sources_relative_to_buildroot())

    for target in targets:
      target.walk(collect_sources)
    return bases, sources

  def createtarget(self, lang, gentarget, dependees):
    if lang == 'java':
      return self._create_java_target(gentarget, dependees)
    elif lang == 'python':
      return self._create_python_target(gentarget, dependees)
    else:
      raise TaskError('Unrecognized protobuf gen lang: %s' % lang)

  def _create_java_target(self, target, dependees):
    genfiles = []
    for source in target.sources_relative_to_source_root():
      path = os.path.join(target.target_base, source)
      genfiles.extend(calculate_genfiles(path, source).get('java', []))
    spec_path = os.path.relpath(self.java_out, get_buildroot())
    spec = '{spec_path}:{name}'.format(spec_path=spec_path, name=target.id)
    address = SyntheticAddress(spec=spec)
    tgt = self.context.add_new_target(address,
                                      JavaLibrary,
                                      derived_from=target,
                                      sources=genfiles,
                                      provides=target.provides,
                                      dependencies=self.javadeps,
                                      excludes=target.payload.excludes)
    for dependee in dependees:
      dependee.inject_dependency(tgt.address)
    return tgt

  def _create_python_target(self, target, dependees):
    genfiles = []
    for source in target.sources_relative_to_source_root():
      path = os.path.join(target.target_base, source)
      genfiles.extend(calculate_genfiles(path, source).get('py', []))
    spec_path = os.path.relpath(self.py_out, get_buildroot())
    spec = '{spec_path}:{name}'.format(spec_path=spec_path, name=target.id)
    address = SyntheticAddress(spec=spec)
    tgt = self.context.add_new_target(address,
                                      PythonLibrary,
                                      derived_from=target,
                                      sources=genfiles,
                                      dependencies=self.pythondeps)
    for dependee in dependees:
      dependee.inject_dependency(tgt.address)
    return tgt


DEFAULT_PACKAGE_PARSER = re.compile(r'^\s*package\s+([^;]+)\s*;\s*$')
OPTION_PARSER = re.compile(r'^\s*option\s+([^ =]+)\s*=\s*([^\s]+)\s*;\s*$')
TYPE_PARSER = re.compile(r'^\s*(enum|message)\s+([^\s{]+).*')
END_TYPE_PARSER = re.compile(r'^\s*}')


def camelcase(string):
  """Convert snake casing where present to camel casing"""
  return ''.join(word.capitalize() for word in string.split('_'))


def calculate_genfiles(path, source):
  with open(path, 'r') as protobuf:
    lines = protobuf.readlines()
    package = ''
    filename = re.sub(r'\.proto$', '', os.path.basename(source))
    outer_class_name = camelcase(filename)
    multiple_files = False
    outer_types = set()
    inner_types = set()
    type_depth = 0
    for line in lines:
      match = DEFAULT_PACKAGE_PARSER.match(line)
      if match:
        package = match.group(1)
      else:
        match = OPTION_PARSER.match(line)
        if match:
          name = match.group(1)
          value = match.group(2)

          def string_value():
            return value.lstrip('"').rstrip('"')

          def bool_value():
            return value == 'true'

          if 'java_package' == name:
            package = string_value()
          elif 'java_outer_classname' == name:
            outer_class_name = string_value()
          elif 'java_multiple_files' == name:
            multiple_files = bool_value()
        else:
          match = TYPE_PARSER.match(line)
          if match:
            type_depth += 1
            type_ = match.group(2)
            if type_depth == 1:
              _record_type(outer_types, type_, match.group(1))
            else:
              _record_type(inner_types, type_, match.group(1))
          else:
            match = END_TYPE_PARSER.match(line)
            if match:
              type_depth -= 1

    # TODO(Eric Ayers) replace with a real lex/parse understanding of protos
    # This is a big hack.  The parsing for finding type definitions is not reliable.
    # See https://github.com/pantsbuild/pants/issues/96
    types = set()
    if multiple_files:
      if type_depth == 0:
        types = outer_types
      else:
        # The parse appears to be flaky, roll all of the found types in.
        types = outer_types.union(inner_types)

    genfiles = defaultdict(set)
    genfiles['py'].update(calculate_python_genfiles(source))
    genfiles['java'].update(calculate_java_genfiles(package,
                                                    outer_class_name,
                                                    types))
    return genfiles


def _record_type(type_set, type_name, type_keyword):
  type_set.add(type_name)
  if type_keyword == 'message':
    type_set.add('%sOrBuilder' % type_name)

def calculate_python_genfiles(source):
  yield re.sub(r'\.proto$', '_pb2.py', source)


def calculate_java_genfiles(package, outer_class_name, types):
  basepath = package.replace('.', '/')

  def path(name):
    return os.path.join(basepath, '%s.java' % name)

  yield path(outer_class_name)
  for type_ in types:
    yield path(type_)
