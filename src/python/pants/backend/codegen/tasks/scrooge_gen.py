# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from collections import defaultdict, namedtuple
import hashlib
import os
import re
import tempfile

from twitter.common.collections import OrderedSet

from pants.backend.codegen.targets.java_thrift_library import JavaThriftLibrary
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.backend.jvm.targets.scala_library import ScalaLibrary
from pants.backend.jvm.tasks.jvm_tool_task_mixin import JvmToolTaskMixin
from pants.backend.jvm.tasks.nailgun_task import NailgunTask
from pants.base.address import SyntheticAddress
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.thrift_util import calculate_compile_sources
from pants.util.dirutil import safe_mkdir, safe_open


CompilerConfig = namedtuple('CompilerConfig', ['name', 'config_section', 'profile',
                                               'main', 'calc_srcs', 'langs'])

_CONFIG_SECTION = 'scrooge-gen'


class Compiler(namedtuple('CompilerConfigWithContext', ('context',) + CompilerConfig._fields)):
  @classmethod
  def from_config(cls, context, config):
    return cls(context, **config._asdict())

  @property
  def jvm_args(self):
    args = self.context.config.getlist(self.config_section, 'jvm_args', default=[])
    args.append('-Dfile.encoding=UTF-8')
    return args

  @property
  def verbose(self):
    if self.context.options.scrooge_gen_quiet is not None:
      return not self.context.options.scrooge_gen_quiet
    else:
      return self.context.config.getbool(self.config_section, 'verbose', default=False)

  @property
  def strict(self):
    return self.context.config.getbool(self.config_section, 'strict', default=False)


# TODO(John Sirois): We used to support multiple incompatible scrooge compilers but no longer do.
# As a result code in this file can be substantially simplified and made more direct.  Do so.
# See: https://github.com/pantsbuild/pants/issues/288
_COMPILERS = [
    CompilerConfig(name='scrooge',
                   config_section=_CONFIG_SECTION,
                   profile='scrooge-gen',
                   main='com.twitter.scrooge.Main',
                   calc_srcs=calculate_compile_sources,
                   langs=frozenset(['scala', 'java'])),
]

_CONFIG_FOR_COMPILER = dict((compiler.name, compiler) for compiler in _COMPILERS)

_TARGET_TYPE_FOR_LANG = dict(scala=ScalaLibrary, java=JavaLibrary)


class ScroogeGen(NailgunTask, JvmToolTaskMixin):
  GenInfo = namedtuple('GenInfo', ['gen', 'deps'])

  class PartialCmd(namedtuple('PC', ['compiler', 'language', 'rpc_style', 'namespace_map'])):
    @property
    def relative_outdir(self):
      namespace_sig = None
      if self.namespace_map:
        sha = hashlib.sha1()
        for ns_from, ns_to in sorted(self.namespace_map):
          sha.update(ns_from)
          sha.update(ns_to)
        namespace_sig = sha.hexdigest()
      output_style = '-'.join(filter(None, (self.language, self.rpc_style, namespace_sig)))
      return os.path.join(self.compiler.name, output_style)

  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    super(ScroogeGen, cls).setup_parser(option_group, args, mkflag)

    option_group.add_option(mkflag('quiet'), dest='scrooge_gen_quiet',
                            action='callback', callback=mkflag.set_bool, default=None,
                            help='[%default] Suppress output, overrides verbose flag in pants.ini.')

  @classmethod
  def product_types(cls):
    return ['java', 'scala']

  def __init__(self, context, workdir):
    super(ScroogeGen, self).__init__(context, workdir)
    self.compiler_for_name = dict((name, Compiler.from_config(context, config))
                                  for name, config in _CONFIG_FOR_COMPILER.items())

    for name, compiler in self.compiler_for_name.items():
      bootstrap_tools = context.config.getlist(compiler.config_section, 'bootstrap-tools',
                                               default=[':%s' % compiler.profile])
      self.register_jvm_tool(compiler.name, bootstrap_tools)

    self.defaults = JavaThriftLibrary.Defaults(context.config)

  @property
  def config_section(self):
    return _CONFIG_SECTION

  # TODO(benjy): Use regular os-located tmpfiles, as we do everywhere else.
  def _tempname(self):
    # don't assume the user's cwd is buildroot
    pants_workdir = self.context.config.getdefault('pants_workdir')
    tmp_dir = os.path.join(pants_workdir, 'tmp')
    safe_mkdir(tmp_dir)
    fd, path = tempfile.mkstemp(dir=tmp_dir, prefix='')
    os.close(fd)
    return path

  def _outdir(self, partial_cmd):
    return os.path.join(self.workdir, partial_cmd.relative_outdir)

  def execute(self):
    targets = self.context.targets()
    self._validate_compiler_configs(targets)

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
      compiler = self.defaults.get_compiler(target)
      language = self.defaults.get_language(target)
      rpc_style = self.defaults.get_rpc_style(target)
      partial_cmd = self.PartialCmd(
          compiler=self.compiler_for_name[compiler],
          language=language,
          rpc_style=rpc_style,
          namespace_map=tuple(sorted(target.namespace_map.items()) if target.namespace_map else ()))
      partial_cmds[partial_cmd].add(target)

    for partial_cmd, tgts in partial_cmds.items():
      gen_files_for_source = self.gen(partial_cmd, tgts)

      relative_outdir = os.path.relpath(self._outdir(partial_cmd), get_buildroot())
      langtarget_by_gentarget = {}
      for target in tgts:
        dependees = dependees_by_gentarget.get(target, [])
        langtarget_by_gentarget[target] = self.createtarget(target, dependees, relative_outdir,
                                                            gen_files_for_source)

      genmap = self.context.products.get(partial_cmd.language)
      for gentarget, langtarget in langtarget_by_gentarget.items():
        genmap.add(gentarget, get_buildroot(), [langtarget])
        for dep in gentarget.dependencies:
          if self.is_gentarget(dep):
            langtarget.inject_dependency(langtarget_by_gentarget[dep].address)

  def gen(self, partial_cmd, targets):
    with self.invalidated(targets, invalidate_dependents=True) as invalidation_check:
      invalid_targets = []
      for vt in invalidation_check.invalid_vts:
        invalid_targets.extend(vt.targets)

      compiler = partial_cmd.compiler
      import_paths, changed_srcs = compiler.calc_srcs(invalid_targets, self.is_gentarget)
      outdir = self._outdir(partial_cmd)
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

        classpath = self.tool_classpath(compiler.name)
        returncode = self.runjava(classpath=classpath,
                                  main=compiler.main,
                                  jvm_options=compiler.jvm_args,
                                  args=args,
                                  workunit_name=compiler.name)
        try:
          if 0 == returncode:
            gen_files_for_source = self.parse_gen_file_map(gen_file_map_path, outdir)
          else:
            gen_files_for_source = None
        finally:
          os.remove(gen_file_map_path)

        if 0 != returncode:
          raise TaskError('java %s ... exited non-zero (%i)' % (compiler.main, returncode))
        self.write_gen_file_map(gen_files_for_source, invalid_targets, outdir)

    return self.gen_file_map(targets, outdir)

  def createtarget(self, gentarget, dependees, outdir, gen_files_for_source):
    assert self.is_gentarget(gentarget)

    def create_target(files, deps, target_type):
      spec = '{spec_path}:{name}'.format(spec_path=outdir, name=gentarget.id)
      address = SyntheticAddress.parse(spec=spec)
      return self.context.add_new_target(address,
                                         target_type,
                                         sources=files,
                                         provides=gentarget.provides,
                                         dependencies=deps,
                                         excludes=gentarget.excludes)

    def create_geninfo(key):
      compiler = self.compiler_for_name[self.defaults.get_compiler(gentarget)]
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
                               create_geninfo(self.defaults.get_language(gentarget)),
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
    target_type = _TARGET_TYPE_FOR_LANG[self.defaults.get_language(target)]
    tgt = create_target(files, deps, target_type)
    tgt.add_labels('codegen')
    for dependee in dependees:
      dependee.inject_dependency(tgt.address)
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
    if not isinstance(target, JavaThriftLibrary):
      return False

    compiler = self.defaults.get_compiler(target)
    if compiler not in self.compiler_for_name.keys():
      return False

    language = self.defaults.get_language(target)
    if language not in self.compiler_for_name[compiler].langs:
      raise TaskError('%s can not generate %s' % (compiler, language))

    return True

  def _validate_compiler_configs(self, targets):
    self._validate(self.defaults, targets)

  @staticmethod
  def _validate(defaults, targets):
    ValidateCompilerConfig = namedtuple('ValidateCompilerConfig', ['language', 'rpc_style'])

    def compiler_config(tgt):
      # Note compiler is not present in this signature. At this time
      # Scrooge and the Apache thrift generators produce identical
      # java sources, and the Apache generator does not produce scala
      # sources. As there's no permutation allowing the creation of
      # incompatible sources with the same language+rpc_style we omit
      # the compiler from the signature at this time.
      return ValidateCompilerConfig(language=defaults.get_language(tgt),
                                    rpc_style=defaults.get_rpc_style(tgt))

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
