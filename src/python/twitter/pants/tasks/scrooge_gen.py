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

import hashlib
import os
import re
import tempfile

from collections import defaultdict, namedtuple

from twitter.common.collections import OrderedSet
from twitter.common.dirutil import safe_mkdir, safe_open

from twitter.pants.base.build_environment import get_buildroot
from twitter.pants.targets import InternalTarget, JavaLibrary, JavaThriftLibrary, ScalaLibrary
from twitter.pants.tasks import TaskError
from twitter.pants.tasks.nailgun_task import NailgunTask
from twitter.pants.thrift_util import (
    calculate_compile_sources,
    calculate_compile_sources_HACK_FOR_SCROOGE_LEGACY)

CompilerConfig = namedtuple('CompilerConfig', ['name', 'config_section', 'profile',
                                               'main', 'calc_srcs', 'langs'])


class Compiler(namedtuple('CompilerConfigWithContext', ('context',) + CompilerConfig._fields)):
  @classmethod
  def fromConfig(cls, context, config):
    return cls(context, **config._asdict())

  @property
  def jvm_args(self):
    args = self.context.config.getlist(self.config_section, 'jvm_args', default=[])
    args.append('-Dfile.encoding=UTF-8')
    return args

  @property
  def outdir(self):
    pants_workdir_fallback = os.path.join(get_buildroot(), '.pants.d')
    workdir_fallback = os.path.join(self.context.config.getdefault('pants_workdir',
                                                                   default=pants_workdir_fallback),
                                    self.name)
    outdir = (self.context.options.scrooge_gen_create_outdir
              or self.context.config.get(self.config_section, 'workdir', default=workdir_fallback))
    return os.path.relpath(outdir)

  @property
  def verbose(self):
    if self.context.options.scrooge_gen_quiet is not None:
      return not self.context.options.scrooge_gen_quiet
    else:
      return self.context.config.getbool(self.config_section, 'verbose', default=False)

  @property
  def strict(self):
    return self.context.config.getbool(self.config_section, 'strict', default=False)


_COMPILERS = [
    CompilerConfig(name='scrooge',
                   config_section='scrooge-gen',
                   profile='scrooge-gen',
                   main='com.twitter.scrooge.Main',
                   calc_srcs=calculate_compile_sources,
                   langs=frozenset(['scala', 'java'])),
    CompilerConfig(name='scrooge-legacy',
                   config_section='scrooge-legacy-gen',
                   profile='scrooge-legacy-gen',
                   main='com.twitter.scrooge.Main',
                   calc_srcs=calculate_compile_sources_HACK_FOR_SCROOGE_LEGACY,
                   langs=frozenset(['scala']))
]

_CONFIG_FOR_COMPILER = dict((compiler.name, compiler) for compiler in _COMPILERS)

_TARGET_TYPE_FOR_LANG = dict(scala=ScalaLibrary, java=JavaLibrary)


class ScroogeGen(NailgunTask):
  GenInfo = namedtuple('GenInfo', ['gen', 'deps'])

  class PartialCmd(namedtuple('PC', ['compiler', 'language', 'rpc_style', 'namespace_map'])):
    @property
    def outdir(self):
      namespace_sig = None
      if self.namespace_map:
        sha = hashlib.sha1()
        for ns_from, ns_to in sorted(self.namespace_map):
          sha.update(ns_from)
          sha.update(ns_to)
        namespace_sig = sha.hexdigest()
      output_style = '-'.join(filter(None, (self.language, self.rpc_style, namespace_sig)))
      return os.path.join(self.compiler.outdir, output_style)

  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    option_group.add_option(mkflag("outdir"), dest="scrooge_gen_create_outdir",
                            help="Emit generated code in to this directory.")
    option_group.add_option(mkflag("quiet"), dest="scrooge_gen_quiet",
                            action="callback", callback=mkflag.set_bool, default=None,
                            help="[%default] Suppress output, overrides verbose flag in pants.ini.")

  def __init__(self, context):
    super(ScroogeGen, self).__init__(context)
    self.compiler_for_name = dict((name, Compiler.fromConfig(context, config))
                                  for name, config in _CONFIG_FOR_COMPILER.items())

    for name, compiler in self.compiler_for_name.items():
      bootstrap_tools = context.config.getlist(compiler.config_section, 'bootstrap-tools',
                                               default=[':%s' % compiler.profile])
      self._jvm_tool_bootstrapper.register_jvm_tool(compiler.name, bootstrap_tools)

  def _tempname(self):
    # don't assume the user's cwd is buildroot
    buildroot = get_buildroot()
    fallback = os.path.join(get_buildroot(), '.pants.d')
    pants_workdir = self.context.config.getdefault('pants_workdir', default=fallback)
    tmp_dir = os.path.join(pants_workdir, 'tmp')
    safe_mkdir(tmp_dir)
    fd, path = tempfile.mkstemp(dir=tmp_dir, prefix='')
    os.close(fd)
    return path

  def execute(self, targets):
    gentargets_by_dependee = self.context.dependents(
      on_predicate=self.is_gentarget,
      from_predicate=lambda t: not self.is_gentarget(t))

    dependees_by_gentarget = defaultdict(set)
    for dependee, tgts in gentargets_by_dependee.items():
      for gentarget in tgts:
        dependees_by_gentarget[gentarget].add(dependee)

    partial_cmds = defaultdict(set)
    gentargets = filter(self.is_gentarget, targets)

    for target in gentargets:
      partial_cmd = self.PartialCmd(
        compiler=self.compiler_for_name[target.compiler],
        language=target.language,
        rpc_style=target.rpc_style,
        namespace_map=tuple(target.namespace_map.items()) if target.namespace_map else ())
      partial_cmds[partial_cmd].add(target)

    for partial_cmd, tgts in partial_cmds.items():
      gen_files_for_source = self.gen(partial_cmd, tgts)

      outdir = partial_cmd.outdir
      langtarget_by_gentarget = {}
      for target in tgts:
        dependees = dependees_by_gentarget.get(target, [])
        langtarget_by_gentarget[target] = self.createtarget(target, dependees, outdir,
                                                            gen_files_for_source)

      genmap = self.context.products.get(partial_cmd.language)
      for gentarget, langtarget in langtarget_by_gentarget.items():
        genmap.add(gentarget, get_buildroot(), [langtarget])
        for dep in gentarget.internal_dependencies:
          if self.is_gentarget(dep):
            langtarget.update_dependencies([langtarget_by_gentarget[dep]])

  def gen(self, partial_cmd, targets):
    with self.invalidated(targets, invalidate_dependents=True) as invalidation_check:
      invalid_targets = []
      for vt in invalidation_check.invalid_vts:
        invalid_targets.extend(vt.targets)

      compiler = partial_cmd.compiler
      import_paths, changed_srcs = compiler.calc_srcs(invalid_targets, self.is_gentarget)
      outdir = partial_cmd.outdir
      if changed_srcs:
        args = []

        for import_path in import_paths:
          args.extend(['--import-path', import_path])

        args.extend(['--language', partial_cmd.language])

        for lhs, rhs in partial_cmd.namespace_map:
          args.extend(['--namespace-map', '%s=%s' % (lhs, rhs)])

        if partial_cmd.rpc_style == 'ostrich':
          args.append('--finagle')
          args.append('--ostrich')
        elif partial_cmd.rpc_style == 'finagle':
          args.append('--finagle')

        args.extend(['--dest', outdir])
        safe_mkdir(outdir)

        if not compiler.strict:
          args.append('--disable-strict')

        if compiler.verbose:
          args.append('--verbose')

        gen_file_map_path = os.path.relpath(self._tempname())
        args.extend(['--gen-file-map', gen_file_map_path])

        args.extend(changed_srcs)

        classpath = self._jvm_tool_bootstrapper.get_jvm_tool_classpath(compiler.name)
        returncode = self.runjava(classpath=classpath,
                                  main=compiler.main,
                                  jvm_options=compiler.jvm_args,
                                  args=args,
                                  workunit_name=compiler.name)
        try:
          if 0 == returncode:
            gen_files_for_source = self.parse_gen_file_map(gen_file_map_path, outdir)
        finally:
          os.remove(gen_file_map_path)

        if 0 != returncode:
          raise TaskError('java %s ... exited non-zero (%i)' % (compiler.main, returncode))
        self.write_gen_file_map(gen_files_for_source, invalid_targets, outdir)

    return self.gen_file_map(targets, outdir)

  def createtarget(self, gentarget, dependees, outdir, gen_files_for_source):
    assert self.is_gentarget(gentarget)

    def create_target(files, deps, target_type):
      return self.context.add_new_target(outdir,
                                         target_type,
                                         name=gentarget.id,
                                         provides=gentarget.provides,
                                         sources=files,
                                         dependencies=deps)

    def create_geninfo(key):
      compiler = self.compiler_for_name[gentarget.compiler]
      gen_info = self.context.config.getdict(compiler.config_section, key,
                                             default={'gen': key,
                                                      'deps': {'service': [], 'structs': []}})
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
    for source in target.sources_relative_to_buildroot():
      services = calculate_services(source)
      genfiles = gen_files_for_source[source]
      has_service = has_service or services
      files.extend(genfiles)
    deps = OrderedSet(geninfo.deps['service' if has_service else 'structs'])
    deps.update(target.dependencies)
    target_type = _TARGET_TYPE_FOR_LANG[target.language]
    tgt = create_target(files, deps, target_type)
    tgt.derived_from = target
    tgt.add_labels('codegen')
    for dependee in dependees:
      if isinstance(dependee, InternalTarget):
        dependee.update_dependencies((tgt,))
      else:
        # TODO(John Sirois): rationalize targets with dependencies.
        # JarLibrary or PythonTarget dependee on the thrift target
        dependee.dependencies.add(tgt)
    return tgt

  def parse_gen_file_map(self, gen_file_map_path, outdir):
    d = defaultdict(set)
    with open(gen_file_map_path, 'r') as deps:
      for dep in deps:
        src, cls = dep.strip().split('->')
        src = os.path.relpath(src.strip())
        cls = os.path.relpath(cls.strip(), outdir)
        d[src].add(cls)
    return d

  def gen_file_map_path_for_target(self, target, outdir):
    return os.path.join(outdir, 'gen-file-map-by-target', target.id)

  def gen_file_map_for_target(self, target, outdir):
    gen_file_map = self.gen_file_map_path_for_target(target, outdir)
    return self.parse_gen_file_map(gen_file_map, outdir)

  def gen_file_map(self, targets, outdir):
    gen_file_map = defaultdict(set)
    for target in targets:
      target_gen_file_map = self.gen_file_map_for_target(target, outdir)
      gen_file_map.update(target_gen_file_map)
    return gen_file_map

  def write_gen_file_map_for_target(self, gen_file_map, target, outdir):
    def calc_srcs(target):
      _, srcs = calculate_compile_sources([target], self.is_gentarget)
      return srcs
    with safe_open(self.gen_file_map_path_for_target(target, outdir), 'w') as f:
      for src in sorted(calc_srcs(target)):
        clss = gen_file_map[src]
        for cls in sorted(clss):
          print('%s -> %s' % (src, os.path.join(outdir, cls)), file=f)

  def write_gen_file_map(self, gen_file_map, targets, outdir):
    for target in targets:
      self.write_gen_file_map_for_target(gen_file_map, target, outdir)

  def is_gentarget(self, target):
    result = (isinstance(target, JavaThriftLibrary)
              and target.compiler in self.compiler_for_name.keys())

    if result and target.language not in self.compiler_for_name[target.compiler].langs:
      raise TaskError("%s can not generate %s" % (target.compiler, target.language))
    return result

  @staticmethod
  def _validate(targets):
    ValidateCompilerConfig = namedtuple('ValidateCompilerConfig', ['language', 'rpc_style'])

    def compiler_config(tgt):
      # Note compiler is not present in this signature. At this time
      # Scrooge and the Apache thrift generators produce identical
      # java sources, and the Apache generator does not produce scala
      # sources. As there's no permutation allowing the creation of
      # incompatible sources with the same language+rpc_style we omit
      # the compiler from the signature at this time.
      return ValidateCompilerConfig(language=tgt.language, rpc_style=tgt.rpc_style)

    mismatched_compiler_configs = defaultdict(set)

    for target in filter(lambda t: isinstance(t, JavaThriftLibrary), targets):
      mycompilerconfig = compiler_config(target)
      def collect(dep):
        if mycompilerconfig != compiler_config(dep):
          mismatched_compiler_configs[target].add(dep)
      target.walk(collect, predicate=lambda t: isinstance(t, JavaThriftLibrary))

    if mismatched_compiler_configs:
      msg = ['Thrift dependency trees must be generated with a uniform compiler configuration.\n\n']
      for tgt in sorted(mismatched_compiler_configs.keys()):
        msg.append('%s - %s\n' % (tgt, compiler_config(tgt)))
        for dep in mismatched_compiler_configs[tgt]:
          msg.append('    %s - %s\n' % (dep, compiler_config(dep)))
      raise TaskError(''.join(msg))


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
