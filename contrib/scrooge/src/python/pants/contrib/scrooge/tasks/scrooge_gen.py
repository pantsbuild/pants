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

from pants.backend.codegen.subsystems.thrift_defaults import ThriftDefaults
from pants.backend.codegen.targets.java_thrift_library import JavaThriftLibrary
from pants.backend.codegen.tasks.simple_codegen_task import SimpleCodegenTask
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.backend.jvm.targets.scala_library import ScalaLibrary
from pants.backend.jvm.tasks.nailgun_task import NailgunTask
from pants.base.address import Address
from pants.base.address_lookup_error import AddressLookupError
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TargetDefinitionException, TaskError
from pants.option.custom_types import dict_option, list_option
from pants.util.dirutil import safe_mkdir, safe_open
from twitter.common.collections import OrderedSet

from pants.contrib.scrooge.tasks.java_thrift_library_fingerprint_strategy import \
  JavaThriftLibraryFingerprintStrategy
from pants.contrib.scrooge.tasks.thrift_util import calculate_compile_sources


_CONFIG_SECTION = 'scrooge-gen'

_TARGET_TYPE_FOR_LANG = dict(scala=ScalaLibrary, java=JavaLibrary, android=JavaLibrary)


class ScroogeGen(SimpleCodegenTask, NailgunTask):

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
    register('--strict', fingerprint=True, default=False, action='store_true', help='Enable strict compilation.')
    register('--jvm-options', default=[], advanced=True, type=list_option,
             help='Use these jvm options when running Scrooge.')
    register('--service-deps', default={}, advanced=True, type=dict_option,
             help='A map of language to targets to add as dependencies of '
                  'synthetic thrift libraries that contain services.')
    register('--structs-deps', default={}, advanced=True, type=dict_option,
             help='A map of language to targets to add as dependencies of '
                  'synthetic thrift libraries that contain structs.')
    cls.register_jvm_tool(register, 'scrooge-gen')

  @classmethod
  def global_subsystems(cls):
    return super(ScroogeGen, cls).global_subsystems() + (ThriftDefaults,)

  @classmethod
  def product_types(cls):
    return ['java', 'scala']

  def __init__(self, *args, **kwargs):
    super(ScroogeGen, self).__init__(*args, **kwargs)
    self._thrift_defaults = ThriftDefaults.global_instance()
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

  def _outdir(self, target):
    return os.path.join(self.workdir, self.codegen_strategy.codegen_workdir_suffix(target))

  def _resolve_deps(self, depmap):
    """Given a map of gen-key=>target specs, resolves the target specs into references."""
    deps = defaultdict(lambda: OrderedSet())
    for category, depspecs in depmap.items():
      dependencies = deps[category]
      for depspec in depspecs:
        try:
          dependencies.update(self.context.resolve(depspec))
        except AddressLookupError as e:
          raise self.DepLookupError("{message}\n  referenced from [{section}] key: "
                                    "gen->deps->{category} in pants.ini".format(
                                      message=e,
                                      section=_CONFIG_SECTION,
                                      category=category
                                    ))
    return deps

  def execute_codegen(self, invalid_targets):
    self._validate_compiler_configs(invalid_targets)
    self._must_have_sources(invalid_targets)

    gentargets_by_dependee = self.context.dependents(
        on_predicate=self.is_gentarget,
        from_predicate=lambda t: not self.is_gentarget(t))

    dependees_by_gentarget = defaultdict(set)
    for dependee, tgts in gentargets_by_dependee.items():
      for gentarget in tgts:
        dependees_by_gentarget[gentarget].add(dependee)

    partial_cmds = defaultdict(set)
    gentargets = filter(self.is_gentarget, invalid_targets)
    if not gentargets:
      return

    for target in gentargets:
      language = self._thrift_defaults.language(target)
      rpc_style = self._thrift_defaults.rpc_style(target)
      partial_cmd = self.PartialCmd(
          language=language,
          rpc_style=rpc_style,
          namespace_map=tuple(sorted(target.namespace_map.items()) if target.namespace_map else ()))
      partial_cmds[partial_cmd].add(target)

    for partial_cmd, tgts in partial_cmds.items():
      self.gen(partial_cmd, tgts)

  def gen(self, partial_cmd, invalid_targets):

    for vt in invalid_targets:
      outdir = self.codegen_workdir(vt)
      import_paths, dummy_changed_srcs = calculate_compile_sources(invalid_targets, self.is_gentarget)
      changed_srcs = vt.sources_relative_to_buildroot()

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

  SERVICE_PARSER = re.compile(r'^\s*service\s+(?:[^\s{]+)')

  def _declares_service(self, source):
    with open(source) as thrift:
      return any(line for line in thrift if self.SERVICE_PARSER.search(line))

  def parse_gen_file_map(self, gen_file_map_path, outdir):
    d = defaultdict(set)
    with safe_open(gen_file_map_path, 'r') as deps:
      for dep in deps:
        src, cls = dep.strip().split('->')
        src = os.path.relpath(src.strip())
        cls = os.path.relpath(cls.strip(), outdir)
        d[src].add(cls)
    return d

  def is_gentarget(self, target):
    if not isinstance(target, JavaThriftLibrary):
      return False

    # We only handle requests for 'scrooge' compilation and not, for example 'thrift', aka the
    # Apache thrift compiler
    if self._thrift_defaults.compiler(target) != 'scrooge':
      return False

    language = self._thrift_defaults.language(target)
    if language not in ('scala', 'java', 'android'):
      raise TaskError('Scrooge can not generate {0}'.format(language))
    return True

  def _validate_compiler_configs(self, targets):
    ValidateCompilerConfig = namedtuple('ValidateCompilerConfig', ['language', 'rpc_style'])

    def compiler_config(tgt):
      # Note compiler is not present in this signature. At this time
      # Scrooge and the Apache thrift generators produce identical
      # java sources, and the Apache generator does not produce scala
      # sources. As there's no permutation allowing the creation of
      # incompatible sources with the same language+rpc_style we omit
      # the compiler from the signature at this time.
      return ValidateCompilerConfig(language=self._thrift_defaults.language(tgt),
                                    rpc_style=self._thrift_defaults.rpc_style(tgt))

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

  def _must_have_sources(self, targets):
    for target in targets:
      if isinstance(target, JavaThriftLibrary) and not target.payload.sources.source_paths:
        raise TargetDefinitionException(target, 'no thrift files found')

  def synthetic_target_type(self, target):
    language = self._thrift_defaults.language(target)
    return _TARGET_TYPE_FOR_LANG[language]

  def synthetic_target_extra_dependencies(self, target):
    has_service = False
    for source in target.sources_relative_to_buildroot():
      has_service = has_service or self._declares_service(source)
    self._depinfo = ScroogeGen.DepInfo(self._resolve_deps(self.get_options().service_deps),
                                       self._resolve_deps(self.get_options().structs_deps))
    language = self._thrift_defaults.language(target)
    deps = OrderedSet(self._depinfo.service[language] if has_service
                      else self._depinfo.structs[language])
    deps.update(target.dependencies)
    return deps
