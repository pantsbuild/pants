# ==================================================================================================
# Copyright 2012 Twitter, Inc.
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

from __future__ import print_function

import os
import re
import tempfile

from collections import defaultdict, namedtuple

from twitter.common.collections import OrderedSet
from twitter.common.dirutil import safe_mkdir

from twitter.pants import get_buildroot
from twitter.pants.binary_util import profile_classpath, JvmCommandLine
from twitter.pants.targets import (
    JavaLibrary,
    JavaThriftLibrary,
    ScalaLibrary)
from twitter.pants.tasks import TaskError
from twitter.pants.tasks.nailgun_task import NailgunTask
from twitter.pants.thrift_util import (
    calculate_compile_sources,
    calculate_compile_sources_HACK_FOR_SCROOGE_LEGACY)

INFO_FOR_COMPILER = { 'scrooge':        { 'config': 'scrooge-gen',
                                          'main':   'com.twitter.scrooge.Main',
                                          'calculate_compile_sources': calculate_compile_sources,
                                          'langs':  frozenset(['scala', 'java']) },

                      'scrooge-legacy': { 'config': 'scrooge-legacy-gen',
                                          'main':   'com.twitter.scrooge.Main',
                                          'calculate_compile_sources':
                                            calculate_compile_sources_HACK_FOR_SCROOGE_LEGACY,
                                          'langs':  frozenset(['scala']) } }

INFO_FOR_LANG = { 'scala':  { 'target_type': ScalaLibrary },
                  'java':   { 'target_type': JavaLibrary  } }


# like an associate array, but sub-sequences may have only one element (uses default)
def value_from_seq_of_seq(seq_of_seq, key, default=None):
  result = default
  for seq in seq_of_seq:
    if len(seq) == 1 and key == seq[0]:
      break
    elif len(seq) == 2 and key == seq[0]:
      result = seq[1]
      break
    elif len(seq) == 0:
      raise ValueError('A sequence of sequences may not have less than one element'
                       ' in a sub-sequence.')
    elif len(seq) > 2:
      raise ValueError('A sequence of sequences may not have more than two elements'
                       ' in a sub-sequence.')
  return result


class ScroogeGen(NailgunTask):
  class GenInfo(object):
    def __init__(self, gen, deps):
      self.gen = gen
      self.deps = deps

  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    option_group.add_option(mkflag("outdir"), dest="scrooge_gen_create_outdir",
                            help="Emit generated code in to this directory.")

  def __init__(self, context, strict=False, verbose=True):
    NailgunTask.__init__(self, context)
    self.strict = strict
    self.verbose = verbose

  def _outdir(self, target):
    compiler_config = INFO_FOR_COMPILER[target.compiler]['config']
    fallback = os.path.join(self.context.config.getdefault('pants_workdir'), target.compiler)
    outdir = (self.context.options.scrooge_gen_create_outdir
              or self.context.config.get(compiler_config, 'workdir', default=fallback))

    outdir = os.path.relpath(outdir)
    return outdir

  def _verbose(self, target):
    compiler_config = INFO_FOR_COMPILER[target.compiler]['config']
    return self.context.config.getbool(compiler_config, 'verbose', default=self.verbose)

  def _strict(self, target):
    compiler_config = INFO_FOR_COMPILER[target.compiler]['config']
    return self.context.config.getbool(compiler_config, 'strict', default=self.strict)

  def _classpth(self, target):
    compiler_config = INFO_FOR_COMPILER[target.compiler]['config']
    return profile_classpath(compiler_config)

  def execute(self, targets):
    gentargets_by_dependee = self.context.dependents(
      on_predicate=is_gentarget,
      from_predicate=lambda t: not is_gentarget(t)
    )
    dependees_by_gentarget = defaultdict(set)
    for dependee, tgts in gentargets_by_dependee.items():
      for gentarget in tgts:
        dependees_by_gentarget[gentarget].add(dependee)

    # TODO(Robert Nielsen): Add optimization to only regenerate the files that have changed
    # initially we could just cache the generated file names and make subsequent invocations faster
    # but a feature like --dry-run will likely be added to scrooge to get these file names (without
    # actually doing the work of generating)
    # AWESOME-1563

    PartialCmd = namedtuple('PartialCmd', ['classpath', 'main', 'opts'])

    partial_cmds = defaultdict(set)
    gentargets = filter(is_gentarget, targets)

    for target in gentargets:
      opts = []

      language = target.language
      opts.append(('--language', language))

      if target.rpc_style == 'ostrich':
        opts.append(('--finagle',))
        opts.append(('--ostrich',))
      elif target.rpc_style == 'finagle':
        opts.append(('--finagle',))

      if target.namespace_map:
        for lhs, rhs in namespace_map([target]).items():
          opts.append(('--namespace-map', '%s=%s' % (lhs, rhs)))

      outdir = self._outdir(target)
      opts.append(('--dest', '%s' % outdir))
      safe_mkdir(outdir)

      if not self._strict(target):
        opts.append(('--disable-strict',))

      if self._verbose(target):
        opts.append(('--verbose',))

      classpath = self._classpth(target)
      main = INFO_FOR_COMPILER[target.compiler]['main']

      partial_cmd = PartialCmd(tuple(classpath), main, tuple(opts))
      partial_cmds[partial_cmd].add(target)

    for partial_cmd, targets in partial_cmds.items():
      classpath = partial_cmd.classpath
      main =      partial_cmd.main
      opts = list(partial_cmd.opts)

      compiler = list(targets)[0].compiler # any target will do (they all have the same compiler)
      calculate_compile_sources = INFO_FOR_COMPILER[compiler]['calculate_compile_sources']
      import_paths, sources = calculate_compile_sources(targets, is_gentarget)

      for import_path in import_paths:
        opts.append(('--import-path', import_path))

      gen_file_map_fd, gen_file_map_path = tempfile.mkstemp()
      os.close(gen_file_map_fd)
      opts.append(('--gen-file-map', gen_file_map_path))

      cmdline = JvmCommandLine(classpath=classpath,
                               main=main,
                               opts=opts,
                               args=sources)

      returncode = cmdline.call()

      if 0 == returncode:
        outdir = value_from_seq_of_seq(opts, '--dest')
        gen_files_for_source = self.parse_gen_file_map(gen_file_map_path, outdir)
      os.remove(gen_file_map_path)

      if 0 != returncode:
        raise TaskError("java %s ... exited non-zero (%i)" % (main, returncode))

      langtarget_by_gentarget = {}
      for target in targets:
        dependees = dependees_by_gentarget.get(target, [])
        langtarget_by_gentarget[target] = self.createtarget(target, dependees, gen_files_for_source)

      genmap = self.context.products.get(language)
      # synmap is a reverse map
      # such as a map of java library target generated from java thrift target
      synmap = self.context.products.get(language + ':rev')
      for gentarget, langtarget in langtarget_by_gentarget.items():
        synmap.add(langtarget, get_buildroot(), [gentarget])
        genmap.add(gentarget, get_buildroot(), [langtarget])
        for dep in gentarget.internal_dependencies:
          if is_gentarget(dep):
            langtarget.update_dependencies([langtarget_by_gentarget[dep]])

  def createtarget(self, gentarget, dependees, gen_files_for_source):
    assert is_gentarget(gentarget)

    def create_target(files, deps, outdir, target_type):
      return self.context.add_new_target(outdir,
                                         target_type,
                                         name=gentarget.id,
                                         provides=gentarget.provides,
                                         sources=files,
                                         dependencies=deps)

    def create_geninfo(key):
      compiler_config = INFO_FOR_COMPILER[gentarget.compiler]['config']
      gen_info = self.context.config.getdict(compiler_config, key)
      gen = gen_info['gen']
      deps = dict()
      for category, depspecs in gen_info['deps'].items():
        dependencies = OrderedSet()
        deps[category] = dependencies
        for depspec in depspecs:
          dependencies.update(self.context.resolve(depspec))
      return self.GenInfo(gen, deps)

    return self._inject_target(gentarget, dependees,
                               create_geninfo(gentarget.language),
                               gen_files_for_source,
                               create_target)

  def _inject_target(self, target, dependees, geninfo, gen_files_for_source, create_target):
    files = []
    has_service = False
    for source_file in target.sources:
      source = os.path.join(target.target_base, source_file)
      services = calculate_services(source)
      genfiles = gen_files_for_source[source]
      has_service = has_service or services
      files.extend(genfiles)
    deps = OrderedSet(geninfo.deps['service' if has_service else 'structs'])
    deps.update(target.dependencies)
    outdir = self._outdir(target)
    target_type = INFO_FOR_LANG[target.language]['target_type']
    tgt = create_target(files, deps, outdir, target_type)
    tgt.id = target.id
    tgt.derived_from = target
    tgt.add_labels('codegen', 'synthetic')
    for dependee in dependees:
      dependee.update_dependencies([tgt])
    return tgt

  def parse_gen_file_map(self, gen_file_map, outdir):
    d = defaultdict(set)
    with open(gen_file_map, 'r') as deps:
      for dep in deps:
        src, cls = dep.strip().split('->')
        src = os.path.relpath(src.strip(), os.path.curdir)
        cls = os.path.relpath(cls.strip(), outdir)
        d[src].add(cls)
    return d

NAMESPACE_PARSER = re.compile(r'^\s*namespace\s+([^\s]+)\s+([^\s]+)\s*$')
TYPE_PARSER = re.compile(r'^\s*(const|enum|exception|service|struct|union)\s+([^\s{]+).*')


# TODO(John Sirois): consolidate thrift parsing to 1 pass instead of 2
def calculate_services(source):
  """Calculates the services generated for the given thrift IDL source.
  Returns an interable of services
  """

  with open(source, 'r') as thrift:
    namespaces = dict()
    types = defaultdict(set)
    for line in thrift:
      match = NAMESPACE_PARSER.match(line)
      if match:
        lang = match.group(1)
        namespace = match.group(2)
        namespaces[lang] = namespace
      else:
        match = TYPE_PARSER.match(line)
        if match:
          typename = match.group(1)
          name = match.group(2)
          types[typename].add(name)

    return types['service']


def is_gentarget(target):
  result = (isinstance(target, JavaThriftLibrary)
            and hasattr(target, 'compiler')
            and hasattr(target, 'language')
            and target.compiler in INFO_FOR_COMPILER)

  if result and target.language not in INFO_FOR_COMPILER[target.compiler]['langs']:
    raise TaskError("%s can not generate %s" % (target.compiler, target.language))
  return result


def namespace_map(targets):
  result = dict()
  target_for_lhs = dict()
  for target in targets:
    if target.namespace_map:
      for lhs, rhs in target.namespace_map.items():
        current_rhs = result.get(lhs)
        if None == current_rhs:
          result[lhs] = rhs
          target_for_lhs[lhs] = target
        elif current_rhs != rhs:
          raise TaskError("Conflicting namespace_map values:\n\t%s {'%s': '%s'}\n\t%s {'%s': '%s'}"
                          % (target_for_lhs[lhs], lhs, current_rhs, target, lhs, rhs))
  return result
