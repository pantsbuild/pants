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

__author__ = 'John Sirois'

import re
import os
import subprocess

from collections import defaultdict

from twitter.common import log
from twitter.common.collections import OrderedSet
from twitter.common.dirutil import safe_mkdir

from twitter.pants import is_jvm, is_python
from twitter.pants.targets import JavaLibrary, JavaProtobufLibrary, PythonLibrary
from twitter.pants.tasks import Task, TaskError
from twitter.pants.tasks.binary_utils import select_binary


class ProtobufGen(Task):
  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    option_group.add_option(mkflag("outdir"), dest="protobuf_gen_create_outdir",
                            help="Emit generated code in to this directory.")

    option_group.add_option(mkflag("lang"), dest="protobuf_gen_langs", default=[],
                            action="append", type="choice", choices=['python', 'java'],
                            help="Force generation of protobuf code for these languages.  Both "
                                 "'python' and 'java' are supported")

  def __init__(self, context, output_dir=None, version=None, javadeps=None, pythondeps=None):
    Task.__init__(self, context)

    self.protobuf_binary = select_binary(
      context.config.get('protobuf-gen', 'supportdir'),
      version or context.config.get('protobuf-gen', 'version'),
      'protoc'
    )
    self.output_dir = (
      output_dir
      or context.options.protobuf_gen_create_outdir
      or context.config.get('protobuf-gen', 'workdir')
    )

    def resolve_deps(key):
      deps = OrderedSet()
      for dep in context.config.getlist('protobuf-gen', 'javadeps'):
        deps.update(context.resolve(dep))
      return deps

    self.javadeps = javadeps or resolve_deps('javadeps')
    self.pythondeps = pythondeps or resolve_deps('pythondeps')
    self.gen_langs = set(context.options.protobuf_gen_langs)

  def invalidate_for(self):
    return self.gen_langs

  def execute(self, targets):
    protobufs = [t for t in targets if ProtobufGen._is_protobuf(t)]
    with self.changed(protobufs, invalidate_dependants=True) as changed_targets:
      safe_mkdir(self.output_dir)

      def forced(lang):
        protobuf_targets = set()
        if lang in self.gen_langs:
          for target in changed_targets:
            target.walk(protobuf_targets.add, ProtobufGen._is_protobuf)
        return protobuf_targets

      protobufs_by_dependee = self.context.dependants(ProtobufGen._is_protobuf)
      dependees_by_protobuf = defaultdict(set)
      for dependee, protobufs in protobufs_by_dependee.items():
        for protobuf in protobufs:
          dependees_by_protobuf[protobuf].add(dependee)

      def find_protobuf_targets(predicate):
        protobuf_targets = set()
        for dependee in protobufs_by_dependee.keys():
          if predicate(dependee):
            tgts = protobufs_by_dependee.pop(dependee)
            for tgt in tgts:
              tgt.walk(protobuf_targets.add, ProtobufGen._is_protobuf)
        return protobuf_targets.intersection(set(changed_targets))

      # TODO(John Sirois): optimization -> find protobuf_targets that share dependees and execute
      # protoc with multiple gens in those cases

      changed = set(changed_targets)

      # Handle jvm
      protobuf_targets = find_protobuf_targets(is_jvm) | forced('java')
      if protobuf_targets:
        java_out = os.path.join(self.output_dir, 'gen-java')
        safe_mkdir(java_out)
        self._gen_protobuf(changed.intersection(protobuf_targets), '--java_out=%s' % java_out)

        java_target_by_protobuf = {}
        for target in protobuf_targets:
          java_target_by_protobuf[target] = self._create_java_target(
            target,
            dependees_by_protobuf.get(target, [])
          )
        for protobuf_target, java_target in java_target_by_protobuf.items():
          for dep in protobuf_target.internal_dependencies:
            java_target.update_dependencies([java_target_by_protobuf[dep]])

      # Handle python
      protobuf_targets = find_protobuf_targets(is_python) | forced('python')
      if protobuf_targets:
        python_out = os.path.join(self.output_dir, 'gen-py')
        safe_mkdir(python_out)
        self._gen_protobuf(changed.intersection(protobuf_targets), '--python_out=%s' % python_out)

        python_target_by_protobuf = {}
        for target in protobuf_targets:
          python_target_by_protobuf[target] = self._create_python_target(
            target,
            dependees_by_protobuf.get(target, [])
          )
        for protobuf_target, python_target in python_target_by_protobuf.items():
          for dep in protobuf_target.internal_dependencies:
            python_target.dependencies.add(python_target_by_protobuf[dep])

      if protobufs_by_dependee:
        raise TaskError

  def _gen_protobuf(self, protobuf_targets, gen):
    bases, sources = self._calculate_sources(protobuf_targets)

    args = [
      self.protobuf_binary,
      gen,
    ]

    for base in bases:
      args.append('--proto_path=%s' % base)

    args.extend(sources)
    log.debug('Executing: %s' % ' '.join(args))
    process = subprocess.Popen(args)
    result = process.wait()
    if result != 0:
      raise TaskError

  @staticmethod
  def _is_protobuf(target):
    return isinstance(target, JavaProtobufLibrary)

  def _calculate_sources(self, thrift_targets):
    bases = set()
    sources = set()
    def collect_sources(target):
      if ProtobufGen._is_protobuf(target):
        bases.add(target.target_base)
        sources.update(os.path.join(target.target_base, source) for source in target.sources)
    for target in thrift_targets:
      target.walk(collect_sources)
    return bases, sources

  def _create_java_target(self, target, dependees):
    gen_java_dir = os.path.join(self.output_dir, 'gen-java')
    genfiles = []
    for source in target.sources:
      path = os.path.join(target.target_base, source)
      genfiles.extend(calculate_genfiles(path, source).get('java', []))
    tgt = self.context.add_target(gen_java_dir,
                                  JavaLibrary,
                                  name=target.id,
                                  sources=genfiles,
                                  dependencies=self.javadeps)
    tgt.id = target.id
    tgt.is_codegen = True
    for dependee in dependees:
      dependee.update_dependencies([tgt])
    return tgt

  def _create_python_target(self, target, dependees):
    gen_python_dir = os.path.join(self.output_dir, 'gen-py')
    genfiles = []
    for source in target.sources:
      path = os.path.join(target.target_base, source)
      genfiles.extend(calculate_genfiles(path, source).get('py', []))
    tgt = self.context.add_target(gen_python_dir,
                                  PythonLibrary,
                                  name=target.id,
                                  sources=genfiles,
                                  module_root=gen_python_dir,
                                  dependencies=self.pythondeps)
    tgt.id = target.id
    for dependee in dependees:
      dependee.dependencies.add(tgt)
    return tgt


DEFAULT_PACKAGE_PARSER = re.compile(r'^\s*package\s+([^;]+)\s*;\s*$')
OPTION_PARSER = re.compile(r'^\s*option\s+([^=]+)\s*=\s*([^\s]+);\s*$')
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

          def string():
            return value.lstrip('"').rstrip('"')

          def bool():
            return value == 'true'

          if 'java_package' == name:
            package = string()
          elif 'java_outer_classname' == name:
            outer_class_name = string()
          elif 'java_multiple_files' == name:
            multiple_files = bool()
        else:
          match = TYPE_PARSER.match(line)
          if match:
            types.add(match.group(1))

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
  for type in types:
    yield path(type)
