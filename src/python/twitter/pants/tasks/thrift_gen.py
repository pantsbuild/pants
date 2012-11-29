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
from twitter.pants.tasks import TaskError
from twitter.pants.tasks.binary_utils import select_binary
from twitter.pants.tasks.code_gen import CodeGen

class ThriftGen(CodeGen):
  class GenInfo(object):
    def __init__(self, gen, deps):
      self.gen = gen
      self.deps = deps

  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    option_group.add_option(mkflag("outdir"), dest="thrift_gen_create_outdir",
                            help="Emit generated code in to this directory.")

    option_group.add_option(mkflag("version"), dest="thrift_version",
                            help="Thrift compiler version.")

    option_group.add_option(mkflag("lang"), dest="thrift_gen_langs",  default=[],
                            action="append", type="choice", choices=['python', 'java'],
                            help="Force generation of thrift code for these languages.  Both "
                                 "'python' and 'java' are supported")

  def __init__(self, context):
    CodeGen.__init__(self, context)

    self.thrift_binary = select_binary(
      context.config.get('thrift-gen', 'supportdir'),
      (context.options.thrift_version
        or context.config.get('thrift-gen', 'version')),
      'thrift'
    )
    self.output_dir = (
      context.options.thrift_gen_create_outdir
      or context.config.get('thrift-gen', 'workdir')
    )
    self.strict = context.config.getbool('thrift-gen', 'strict')
    self.verbose = context.config.getbool('thrift-gen', 'verbose')

    def create_geninfo(key):
      gen_info = context.config.getdict('thrift-gen', key)
      gen = gen_info['gen']
      deps = OrderedSet()
      for dep in gen_info['deps']:
        deps.update(context.resolve(dep))
      return ThriftGen.GenInfo(gen, deps)

    self.gen_java = create_geninfo('java')
    self.gen_python = create_geninfo('python')

    self.gen_langs = set(context.options.thrift_gen_langs)
    for lang in ('java', 'python'):
      if self.context.products.isrequired(lang):
        self.gen_langs.add(lang)


  def invalidate_for(self):
    return self.gen_langs

  def invalidate_for_files(self):
    return [self.thrift_binary]

  def is_gentarget(self, target):
    return isinstance(target, JavaThriftLibrary) or isinstance(target, PythonThriftLibrary)

  def is_forced(self, lang):
    return lang in self.gen_langs

  def genlangs(self):
    return dict(java=is_jvm, python=is_python)

  def genlang(self, lang, targets):
    bases, sources = self._calculate_sources(targets)

    if lang == 'java':
      gen = self.gen_java.gen
    elif lang == 'python':
      gen = self.gen_python.gen
    else:
      raise TaskError('Unrecognized thrift gen lang: %s' % lang)

    safe_mkdir(self.output_dir)

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

    # TODO(John Sirois): Use map sources to targets and invalidate less thrift targets on failure.
    if sum(p.wait() for p in processes) != 0:
      raise TaskError

  def _calculate_sources(self, thrift_targets):
    bases = set()
    sources = set()
    def collect_sources(target):
      if self.is_gentarget(target):
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

  def createtarget(self, lang, gentarget, dependees):
    if lang == 'java':
      return self._create_java_target(gentarget, dependees)
    elif lang == 'python':
      return self._create_python_target(gentarget, dependees)
    else:
      raise TaskError('Unrecognized thrift gen lang: %s' % lang)

  def _create_java_target(self, target, dependees):
    gen_java_dir = os.path.join(self.output_dir, 'gen-java')
    genfiles = []
    for source in target.sources:
      genfiles.extend(calculate_genfiles(os.path.join(target.target_base, source)).get('java', []))
    tgt = self.context.add_new_target(gen_java_dir,
                                      JavaLibrary,
                                      name=target.id,
                                      provides=target.provides,
                                      sources=genfiles,
                                      dependencies=self.gen_java.deps,
                                      derived_from=target)
    tgt.id = target.id + '.thrift_gen'
    tgt.add_label('codegen')
    for dependee in dependees:
      dependee.update_dependencies([tgt])
    return tgt

  def _create_python_target(self, target, dependees):
    gen_python_dir = os.path.join(self.output_dir, 'gen-py')
    genfiles = []
    for source in target.sources:
      genfiles.extend(calculate_genfiles(os.path.join(target.target_base, source)).get('py', []))
    tgt = self.context.add_new_target(gen_python_dir,
                                      PythonLibrary,
                                      name=target.id,
                                      sources=genfiles,
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
