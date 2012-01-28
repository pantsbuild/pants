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

import os
import re
import subprocess

from collections import defaultdict

from twitter.common import log
from twitter.common.collections import OrderedSet
from twitter.common.dirutil import safe_mkdir

from twitter.pants import is_jvm, is_python
from twitter.pants.targets import JavaLibrary, JavaThriftLibrary, PythonLibrary, PythonThriftLibrary
from twitter.pants.tasks import Task, TaskError
from twitter.pants.tasks.binary_utils import select_binary

class ThriftGen(Task):
  class GenInfo(object):
    def __init__(self, gen, deps):
      self.gen = gen
      self.deps = deps

  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    option_group.add_option(mkflag("outdir"), dest="thrift_gen_create_outdir",
                            help="Emit generated code in to this directory.")

    option_group.add_option(mkflag("lang"), dest="thrift_gen_langs",  default=[],
                            action="append", type="choice", choices=['python', 'java'],
                            help="Force generation of thrift code for these languages.  Both "
                                 "'python' and 'java' are supported")

  def __init__(self, context, output_dir=None, version=None, java_geninfo=None, python_geninfo=None,
               strict=None, verbose=None):

    Task.__init__(self, context)

    self.thrift_binary = select_binary(
      context.config.get('thrift-gen', 'supportdir'),
      version or context.config.get('thrift-gen', 'version'),
      'thrift'
    )
    self.output_dir = (
      output_dir
      or context.options.thrift_gen_create_outdir
      or context.config.get('thrift-gen', 'workdir')
    )
    self.strict = strict or context.config.getbool('thrift-gen', 'strict')
    self.verbose = verbose or context.config.getbool('thrift-gen', 'verbose')

    def create_geninfo(key):
      gen_info = context.config.getdict('thrift-gen', key)
      gen = gen_info['gen']
      deps = OrderedSet()
      for dep in gen_info['deps']:
        deps.update(context.resolve(dep))
      return ThriftGen.GenInfo(gen, deps)

    self.gen_java = java_geninfo or create_geninfo('java')
    self.gen_python = python_geninfo or create_geninfo('python')
    self.gen_langs = set(context.options.thrift_gen_langs)

  def invalidate_for(self):
    return self.gen_langs

  def execute(self, targets):
    thrifts = [t for t in targets if ThriftGen._is_thrift(t)]
    with self.changed(thrifts, invalidate_dependants=True) as changed_targets:
      safe_mkdir(self.output_dir)

      def forced(lang):
        thrift_targets = set()
        if lang in self.gen_langs:
          for target in targets:
            target.walk(thrift_targets.add, ThriftGen._is_thrift)
        return thrift_targets

      thrifts_by_dependee = self.context.dependants(ThriftGen._is_thrift)
      dependees_by_thrift = defaultdict(set)
      for dependee, thrifts in thrifts_by_dependee.items():
        for thrift in thrifts:
          dependees_by_thrift[thrift].add(dependee)

      def find_thrift_targets(predicate):
        thrift_targets = set()
        for dependee in thrifts_by_dependee.keys():
          if predicate(dependee):
            tgts = thrifts_by_dependee.pop(dependee)
            for tgt in tgts:
              tgt.walk(thrift_targets.add, ThriftGen._is_thrift)
        return thrift_targets.intersection(set(targets))

      # TODO(John Sirois): optimization -> find thrift_targets that share dependees and execute
      # thrift with multiple gens in those cases

      changed = set(changed_targets)

      # Handle jvm
      thrift_targets = find_thrift_targets(is_jvm) | forced('java')
      if thrift_targets:
        self._gen_thrift(changed.intersection(thrift_targets), self.gen_java.gen)

        java_target_by_thrift = {}
        for target in thrift_targets:
          java_target_by_thrift[target] = self._create_java_target(
            target,
            dependees_by_thrift.get(target, [])
          )
        for thrift_target, java_target in java_target_by_thrift.items():
          for dep in thrift_target.internal_dependencies:
            java_target.update_dependencies([java_target_by_thrift[dep]])

      # Handle python
      thrift_targets = find_thrift_targets(is_python) | forced('python')
      if thrift_targets:
        self._gen_thrift(changed.intersection(thrift_targets), self.gen_python.gen)

        python_target_by_thrift = {}
        for target in thrift_targets:
          python_target_by_thrift[target] = self._create_python_target(
            target,
            dependees_by_thrift.get(target, [])
          )
        for thrift_target, python_target in python_target_by_thrift.items():
          for dep in thrift_target.internal_dependencies:
            python_target.dependencies.add(python_target_by_thrift[dep])

      if thrifts_by_dependee:
        raise TaskError

  def _gen_thrift(self, thrift_targets, gen):
    bases, sources = self._calculate_sources(thrift_targets)

    args = [
      self.thrift_binary,
      '--gen', gen,
      '-recurse',
      '-o', self.output_dir,
    ]

    if self.strict:
      args.append('-strict')
    if self.verbose:
      args.append('-verbose')
    for base in bases:
      args.extend(('-I', base))

    processes = []
    for source in sources:
      cmd = args[:]
      cmd.append(source)
      log.debug('Executing: %s' % ' '.join(cmd))
      processes.append(subprocess.Popen(cmd))

    # TODO(John Sirois): Use map sources to targets and use TargetError to invalidate less thrift
    # targets onfailure
    if sum(p.wait() for p in processes) != 0:
      raise TaskError

  @staticmethod
  def _is_thrift(target):
    return isinstance(target, JavaThriftLibrary) or isinstance(target, PythonThriftLibrary)

  def _calculate_sources(self, thrift_targets):
    bases = set()
    sources = set()
    def collect_sources(target):
      if ThriftGen._is_thrift(target):
        bases.add(target.target_base)
        sources.update(os.path.join(target.target_base, source) for source in target.sources)
    for target in thrift_targets:
      target.walk(collect_sources)
    sources = self._find_root_sources(bases, sources)
    return bases, sources

  def _find_root_sources(self, bases, sources):
    root_sources = set(sources)
    for source in sources:
      root_sources.difference_update(find_includes(bases, source))
    return root_sources

  def _create_java_target(self, target, dependees):
    gen_java_dir = os.path.join(self.output_dir, 'gen-java')
    genfiles = []
    for source in target.sources:
      genfiles.extend(calculate_genfiles(os.path.join(target.target_base, source)).get('java', []))
    tgt = self.context.add_target(gen_java_dir,
                                  JavaLibrary,
                                  name=target.id,
                                  provides=target.provides,
                                  sources=genfiles,
                                  dependencies=self.gen_java.deps)
    tgt.id = target.id
    tgt.is_codegen = True
    for dependee in dependees:
      dependee.update_dependencies([tgt])
    return tgt

  def _create_python_target(self, target, dependees):
    gen_python_dir = os.path.join(self.output_dir, 'gen-py')
    genfiles = []
    for source in target.sources:
      genfiles.extend(calculate_genfiles(os.path.join(target.target_base, source)).get('py', []))
    tgt = self.context.add_target(gen_python_dir,
                                  PythonLibrary,
                                  name=target.id,
                                  sources=genfiles,
                                  module_root=gen_python_dir,
                                  dependencies=self.gen_python.deps)
    tgt.id = target.id
    for dependee in dependees:
      dependee.dependencies.add(tgt)
    return tgt


INCLUDE_PARSER = re.compile(r'^\s*include\s+"([^"]+)"\s*$')


def find_includes(bases, source):
  all_bases = [os.path.dirname(source)]
  all_bases.extend(bases)

  includes = set()
  with open(source, 'r') as thrift:
    for line in thrift.readlines():
      match = INCLUDE_PARSER.match(line)
      if match:
        capture = match.group(1)
        for base in all_bases:
          include = os.path.join(base, capture)
          if os.path.exists(include):
            log.debug('%s has include %s' % (source, include))
            includes.add(include)
  return includes


NAMESPACE_PARSER = re.compile(r'^\s*namespace\s+([^\s]+)\s+([^\s]+)\s*$')
TYPE_PARSER = re.compile(r'^\s*(const|enum|exception|service|struct|union)\s+([^\s{]+).*')


# TODO(John Sirois): consolidate thrift parsing to 1 pass instead of 2
def calculate_genfiles(source):
  with open(source, 'r') as thrift:
    lines = thrift.readlines()
    namespaces = {}
    types = defaultdict(set)
    for line in lines:
      match = NAMESPACE_PARSER.match(line)
      if match:
        lang = match.group(1)
        namespace = match.group(2)
        namespaces[lang] = namespace
      else:
        match = TYPE_PARSER.match(line)
        if match:
          type = match.group(1)
          name = match.group(2)
          types[type].add(name)

    genfiles = defaultdict(set)

    namespace = namespaces.get('py')
    if namespace:
      genfiles['py'].update(calculate_python_genfiles(namespace, types))

    namespace = namespaces.get('java')
    if namespace:
      genfiles['java'].update(calculate_java_genfiles(namespace, types))

    return genfiles


def calculate_python_genfiles(namespace, types):
  basepath = namespace.replace('.', '/')
  def path(name):
    return os.path.join(basepath, '%s.py' % name)
  yield path('__init__')
  if 'const' in types:
    yield path('constants')
  if set(['enum', 'exception', 'struct', 'union']) & set(types.keys()):
    yield path('ttypes')
  for service in types['service']:
    yield path(service)
    yield os.path.join(basepath, '%s-remote' % service)


def calculate_java_genfiles(namespace, types):
  basepath = namespace.replace('.', '/')
  def path(name):
    return os.path.join(basepath, '%s.java' % name)
  if 'const' in types:
    yield path('Constants')
  for type in ['enum', 'exception', 'service', 'struct', 'union']:
    for name in types[type]:
      yield path(name)
