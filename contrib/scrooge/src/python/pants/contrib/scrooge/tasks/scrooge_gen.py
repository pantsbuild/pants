# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import hashlib
import os
import re
import tempfile
from collections import defaultdict, namedtuple

from pants.backend.codegen.targets.java_thrift_library import JavaThriftLibrary
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.backend.jvm.targets.scala_library import ScalaLibrary
from pants.backend.jvm.tasks.jvm_tool_task_mixin import JvmToolTaskMixin
from pants.backend.jvm.tasks.nailgun_task import NailgunTask
from pants.base.address import SyntheticAddress
from pants.base.address_lookup_error import AddressLookupError
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.option.options import Options
from pants.thrift_util import calculate_compile_sources
from pants.util.dirutil import safe_mkdir, safe_open
from twitter.common.collections import OrderedSet

from pants.contrib.scrooge.tasks.java_thrift_library_fingerprint_strategy import \
  JavaThriftLibraryFingerprintStrategy


_CONFIG_SECTION = 'scrooge-gen'

_TARGET_TYPE_FOR_LANG = dict(scala=ScalaLibrary, java=JavaLibrary)


class ScroogeGen(NailgunTask, JvmToolTaskMixin):

  DepInfo = namedtuple('DepInfo', ['service', 'structs'])

  class DepLookupError(AddressLookupError):
    """Thrown when a dependency can't be found."""
    pass

  class PartialCmd(namedtuple('PC', ['language', 'rpc_style', 'namespace_map'])):
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
      return output_style

  @classmethod
  def register_options(cls, register):
    super(ScroogeGen, cls).register_options(register)
    register('--verbose', default=False, action='store_true', help='Emit verbose output.')
    register('--strict', default=False, action='store_true', help='Enable strict compilation.')
    register('--jvm-options', default=[], advanced=True, type=Options.list,
             help='Use these jvm options when running Scrooge.')
    register('--service-deps', default={}, advanced=True, type=Options.dict,
             help='A map of language to targets to add as dependencies of '
                  'synthetic thrift libraries that contain services.')
    register('--structs-deps', default={}, advanced=True, type=Options.dict,
             help='A map of language to targets to add as dependencies of '
                  'synthetic thrift libraries that contain structs.')
    cls.register_jvm_tool(register, 'scrooge-gen')

  @classmethod
  def product_types(cls):
    return ['java', 'scala']

  def __init__(self, *args, **kwargs):
    super(ScroogeGen, self).__init__(*args, **kwargs)
    self._depinfo = None

  @property
  def config_section(self):
    return _CONFIG_SECTION

  # TODO(benjy): Use regular os-located tmpfiles, as we do everywhere else.
  def _tempname(self):
    # don't assume the user's cwd is buildroot
    pants_workdir = self.get_options().pants_workdir
    tmp_dir = os.path.join(pants_workdir, 'tmp')
    safe_mkdir(tmp_dir)
    fd, path = tempfile.mkstemp(dir=tmp_dir, prefix='')
    os.close(fd)
    return path

  def _outdir(self, partial_cmd):
    return os.path.join(self.workdir, partial_cmd.relative_outdir)

  def _resolve_deps(self, depmap):
    """Given a map of gen-key=>target specs, resolves the target specs into references."""
    deps = defaultdict(lambda: OrderedSet())
    for category, depspecs in depmap.items():
      dependencies = deps[category]
      for depspec in depspecs:
        try:
          dependencies.update(self.context.resolve(depspec))
        except AddressLookupError as e:
          raise self.DepLookupError("{message}\n  referenced from [{section}] key: " \
                                    "gen->deps->{category} in pants.ini".format(
                                      message=e,
                                      section=_CONFIG_SECTION,
                                      category=category
                                    ))
    return deps

  def execute(self):
    targets = self.context.targets()
    self._validate_compiler_configs(targets)

    gentargets_by_dependee = self.context.dependents(
        on_predicate=self.is_scroogetarget,
        from_predicate=lambda t: not self.is_scroogetarget(t))

    dependees_by_gentarget = defaultdict(set)
    for dependee, tgts in gentargets_by_dependee.items():
      for gentarget in tgts:
        dependees_by_gentarget[gentarget].add(dependee)

    partial_cmds = defaultdict(set)
    gentargets = filter(self.is_scroogetarget, targets)
    if not gentargets:
      return

    self._depinfo = ScroogeGen.DepInfo(self._resolve_deps(self.get_options().service_deps),
                                       self._resolve_deps(self.get_options().structs_deps))

    for target in gentargets:
      language = target.language(self.context.options)
      rpc_style = target.rpc_style(self.context.options)
      partial_cmd = self.PartialCmd(
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
          if self.is_scroogetarget(dep):
            langtarget.inject_dependency(langtarget_by_gentarget[dep].address)

  def gen(self, partial_cmd, targets):
    fp_strategy = JavaThriftLibraryFingerprintStrategy(self.context.options)
    with self.invalidated(targets, fingerprint_strategy=fp_strategy,
                          invalidate_dependents=True) as invalidation_check:
      invalid_targets = []
      for vt in invalidation_check.invalid_vts:
        invalid_targets.extend(vt.targets)

      import_paths, changed_srcs = calculate_compile_sources(invalid_targets, self.is_scroogetarget)
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

        if not self.get_options().strict:
          args.append('--disable-strict')

        if self.get_options().verbose:
          args.append('--verbose')

        gen_file_map_path = os.path.relpath(self._tempname())
        args.extend(['--gen-file-map', gen_file_map_path])

        args.extend(changed_srcs)

        classpath = self.tool_classpath('scrooge-gen')
        jvm_options = list(self.get_options().jvm_options)
        jvm_options.append('-Dfile.encoding=UTF-8')
        returncode = self.runjava(classpath=classpath,
                                  main='com.twitter.scrooge.Main',
                                  jvm_options=jvm_options,
                                  args=args,
                                  workunit_name='scrooge-gen')
        try:
          if 0 == returncode:
            gen_files_for_source = self.parse_gen_file_map(gen_file_map_path, outdir)
          else:
            gen_files_for_source = None
        finally:
          os.remove(gen_file_map_path)

        if 0 != returncode:
          raise TaskError('Scrooge compiler exited non-zero ({0})'.format(returncode))
        self.write_gen_file_map(gen_files_for_source, invalid_targets, outdir)

    return self.gen_file_map(targets, outdir)

  def createtarget(self, gentarget, dependees, outdir, gen_files_for_source):
    assert self.is_scroogetarget(gentarget)

    def create_target(files, deps, target_type):
      spec = '{spec_path}:{name}'.format(spec_path=outdir, name=gentarget.id)
      address = SyntheticAddress.parse(spec=spec)
      return self.context.add_new_target(address,
                                         target_type,
                                         sources=files,
                                         provides=gentarget.provides,
                                         dependencies=deps,
                                         excludes=gentarget.excludes,
                                         derived_from=gentarget)

    return self._inject_target(gentarget, dependees,
                               gen_files_for_source,
                               create_target)

  def _inject_target(self, target, dependees, gen_files_for_source, create_target):
    files = []
    has_service = False
    for source in target.sources_relative_to_buildroot():
      services = calculate_services(source)
      genfiles = gen_files_for_source[source]
      has_service = has_service or services
      files.extend(genfiles)
    language = target.language(self.context.options)
    target_type = _TARGET_TYPE_FOR_LANG[language]
    deps = OrderedSet(self._depinfo.service[language] if has_service else self._depinfo.structs[language])
    deps.update(target.dependencies)
    tgt = create_target(files, deps, target_type)
    tgt.add_labels('codegen')
    for dependee in dependees:
      dependee.inject_dependency(tgt.address)
    return tgt

  def parse_gen_file_map(self, gen_file_map_path, outdir):
    d = defaultdict(set)
    with safe_open(gen_file_map_path, 'r') as deps:
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
      _, srcs = calculate_compile_sources([target], self.is_scroogetarget)
      return srcs
    with safe_open(self.gen_file_map_path_for_target(target, outdir), 'w') as f:
      for src in sorted(calc_srcs(target)):
        clss = gen_file_map[src]
        for cls in sorted(clss):
          print('%s -> %s' % (src, os.path.join(outdir, cls)), file=f)

  def write_gen_file_map(self, gen_file_map, targets, outdir):
    for target in targets:
      self.write_gen_file_map_for_target(gen_file_map, target, outdir)

  def is_scroogetarget(self, target):
    if not isinstance(target, JavaThriftLibrary):
      return False

    # We only handle requests for 'scrooge' compilation and not, for example 'thrift', aka the
    # Apache thrift compiler
    if target.compiler(self.context.options) != 'scrooge':
      return False

    language = target.language(self.context.options)
    if language not in ('scala', 'java'):
      raise TaskError('Scrooge can not generate {0}'.format(language))
    return True

  def _validate_compiler_configs(self, targets):
    self._validate(self.context.options, targets)

  @staticmethod
  def _validate(options, targets):
    ValidateCompilerConfig = namedtuple('ValidateCompilerConfig', ['language', 'rpc_style'])

    def compiler_config(tgt):
      # Note compiler is not present in this signature. At this time
      # Scrooge and the Apache thrift generators produce identical
      # java sources, and the Apache generator does not produce scala
      # sources. As there's no permutation allowing the creation of
      # incompatible sources with the same language+rpc_style we omit
      # the compiler from the signature at this time.
      return ValidateCompilerConfig(language=tgt.language(options),
                                    rpc_style=tgt.rpc_style(options))

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
