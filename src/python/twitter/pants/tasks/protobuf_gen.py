# ==================================================================================================
# Copyright 2011 Twitter, Inc.
# --------------------------------------------------------------------------------------------------
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this work except in compliance with the License.
# You may obtain a copy of the License in the LICENSE file, or at:
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==================================================================================================

import os
import re
import subprocess

from collections import defaultdict

from twitter.common import log
from twitter.common.collections import OrderedSet
from twitter.common.dirutil import safe_mkdir

from twitter.pants.binary_util import select_binary
from twitter.pants.targets import JavaLibrary, JavaProtobufLibrary, PythonLibrary

from .code_gen import CodeGen

from twitter.pants.tasks import TaskError


class ProtobufGen(CodeGen):
  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    option_group.add_option(mkflag("outdir"), dest="protobuf_gen_create_outdir",
                            help="Emit generated code in to this directory.")

    option_group.add_option(mkflag("lang"), dest="protobuf_gen_langs", default=[],
                            action="append", type="choice", choices=['python', 'java'],
                            help="Force generation of protobuf code for these languages.  Both "
                                 "'python' and 'java' are supported")

  def __init__(self, context):
    CodeGen.__init__(self, context)

    self.protoc_supportdir = self.context.config.get('protobuf-gen', 'supportdir')
    self.protoc_version = self.context.config.get('protobuf-gen', 'version')
    self.output_dir = (context.options.protobuf_gen_create_outdir or
                       context.config.get('protobuf-gen', 'workdir'))

    def resolve_deps(key):
      deps = OrderedSet()
      for dep in context.config.getlist('protobuf-gen', key):
        deps.update(context.resolve(dep))
      return deps

    self.javadeps = resolve_deps('javadeps')
    self.java_out = os.path.join(self.output_dir, 'gen-java')

    self.pythondeps = resolve_deps('pythondeps')
    self.py_out = os.path.join(self.output_dir, 'gen-py')

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
      safe_mkdir(self.java_out)
      gen = '--java_out=%s' % self.java_out
    elif lang == 'python':
      safe_mkdir(self.py_out)
      gen = '--python_out=%s' % self.py_out
    else:
      raise TaskError('Unrecognized protobuf gen lang: %s' % lang)

    args = [
      self.protobuf_binary,
      gen
    ]

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
    for source in target.sources:
      path = os.path.join(target.target_base, source)
      genfiles.extend(calculate_genfiles(path, source).get('java', []))
    tgt = self.context.add_new_target(self.java_out,
                                      JavaLibrary,
                                      name=target.id,
                                      provides=target.provides,
                                      sources=genfiles,
                                      dependencies=self.javadeps,
                                      derived_from=target)
    tgt.id = target.id + '.protobuf_gen'
    for dependee in dependees:
      dependee.update_dependencies([tgt])
    return tgt

  def _create_python_target(self, target, dependees):
    genfiles = []
    for source in target.sources:
      path = os.path.join(target.target_base, source)
      genfiles.extend(calculate_genfiles(path, source).get('py', []))
    tgt = self.context.add_new_target(self.py_out,
                                      PythonLibrary,
                                      name=target.id,
                                      sources=genfiles,
                                      dependencies=self.pythondeps)
    tgt.id = target.id
    for dependee in dependees:
      dependee.dependencies.add(tgt)
    return tgt


DEFAULT_PACKAGE_PARSER = re.compile(r'^\s*package\s+([^;]+)\s*;\s*$')
OPTION_PARSER = re.compile(r'^\s*option\s+([^ =]+)\s*=\s*([^\s]+)\s*;\s*$')
TYPE_PARSER = re.compile(r'^\s*(enum|message)\s+([^\s{]+).*')


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
    types = set()
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
            type_ = match.group(2)
            types.add(type_)
            if match.group(1) == 'message':
              types.add('%sOrBuilder' % type_)

    genfiles = defaultdict(set)
    genfiles['py'].update(calculate_python_genfiles(source))
    genfiles['java'].update(calculate_java_genfiles(package,
                                                    outer_class_name,
                                                    types if multiple_files else []))
    return genfiles


def calculate_python_genfiles(source):
  yield re.sub(r'\.proto$', '_pb2.py', source)


def calculate_java_genfiles(package, outer_class_name, types):
  basepath = package.replace('.', '/')

  def path(name):
    return os.path.join(basepath, '%s.java' % name)

  yield path(outer_class_name)
  for type_ in types:
    yield path(type_)
