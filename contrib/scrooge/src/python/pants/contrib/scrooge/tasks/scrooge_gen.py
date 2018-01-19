# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import re
import tempfile
from collections import defaultdict, namedtuple

from pants.backend.codegen.thrift.java.java_thrift_library import JavaThriftLibrary
from pants.backend.codegen.thrift.java.thrift_defaults import ThriftDefaults
from pants.backend.jvm.tasks.nailgun_task import NailgunTask
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TargetDefinitionException, TaskError
from pants.build_graph.address import Address
from pants.build_graph.address_lookup_error import AddressLookupError
from pants.task.simple_codegen_task import SimpleCodegenTask
from pants.util.dirutil import safe_mkdir, safe_open
from pants.util.memo import memoized_method, memoized_property
from twitter.common.collections import OrderedSet

from pants.contrib.scrooge.tasks.java_thrift_library_fingerprint_strategy import \
  JavaThriftLibraryFingerprintStrategy
from pants.contrib.scrooge.tasks.thrift_util import calculate_compile_sources


_RPC_STYLES = frozenset(['sync', 'finagle', 'ostrich'])


class ScroogeGen(SimpleCodegenTask, NailgunTask):

  DepInfo = namedtuple('DepInfo', ['service', 'structs'])
  PartialCmd = namedtuple('PartialCmd', [
    'language', 
    'namespace_map', 
    'default_java_namespace', 
    'include_paths', 
    'compiler_args'
  ])

  @classmethod
  def register_options(cls, register):
    super(ScroogeGen, cls).register_options(register)
    register('--verbose', type=bool, help='Emit verbose output.')
    register('--strict', fingerprint=True, type=bool,
             help='Enable strict compilation.')
    register('--service-deps', default={}, advanced=True, type=dict,
             help='A map of language to targets to add as dependencies of '
                  'synthetic thrift libraries that contain services.')
    register('--structs-deps', default={}, advanced=True, type=dict,
             help='A map of language to targets to add as dependencies of '
                  'synthetic thrift libraries that contain structs.')
    register('--service-exports', default={}, advanced=True, type=dict,
             help='A map of language to targets to add as exports of '
                  'synthetic thrift libraries that contain services.')
    register('--structs-exports', default={}, advanced=True, type=dict,
             help='A map of language to targets to add as exports of '
                  'synthetic thrift libraries that contain structs.')
    register('--target-types',
             default={'scala': 'scala_library', 'java': 'java_library', 'android': 'java_library'},
             advanced=True,
             type=dict,
             help='Registered target types.')
    cls.register_jvm_tool(register, 'scrooge-gen')

  @classmethod
  def subsystem_dependencies(cls):
    return super(ScroogeGen, cls).subsystem_dependencies() + (ThriftDefaults,)

  @classmethod
  def product_types(cls):
    return ['java', 'scala']

  @classmethod
  def implementation_version(cls):
    return super(ScroogeGen, cls).implementation_version() + [('ScroogeGen', 3)]

  @classmethod
  def get_fingerprint_strategy(cls):
    return JavaThriftLibraryFingerprintStrategy(ThriftDefaults.global_instance())

  def __init__(self, *args, **kwargs):
    super(ScroogeGen, self).__init__(*args, **kwargs)
    self._thrift_defaults = ThriftDefaults.global_instance()
    self._depinfo = None

  # TODO(benjy): Use regular os-located tmpfiles, as we do everywhere else.
  def _tempname(self):
    # don't assume the user's cwd is buildroot
    pants_workdir = self.get_options().pants_workdir
    tmp_dir = os.path.join(pants_workdir, 'tmp')
    safe_mkdir(tmp_dir)
    fd, path = tempfile.mkstemp(dir=tmp_dir, prefix='')
    os.close(fd)
    return path

  def _resolve_deps(self, depmap):
    """Given a map of gen-key=>target specs, resolves the target specs into references."""
    deps = defaultdict(lambda: OrderedSet())
    for category, depspecs in depmap.items():
      dependencies = deps[category]
      for depspec in depspecs:
        dep_address = Address.parse(depspec)
        try:
          self.context.build_graph.maybe_inject_address_closure(dep_address)
          dependencies.add(self.context.build_graph.get_target(dep_address))
        except AddressLookupError as e:
          raise AddressLookupError('{}\n  referenced from {} scope'.format(e, self.options_scope))
    return deps

  def _validate_language(self, target):
    language = self._thrift_defaults.language(target)
    if language not in self._registered_language_aliases():
      raise TargetDefinitionException(
          target,
          'language {} not supported: expected one of {}.'.format(language, self._registered_language_aliases().keys()))
    return language

  def _validate_rpc_style(self, target):
    rpc_style = self._thrift_defaults.rpc_style(target)
    if rpc_style not in _RPC_STYLES:
      raise TargetDefinitionException(
          target,
          'rpc_style {} not supported: expected one of {}.'.format(rpc_style, _RPC_STYLES))
    return rpc_style

  @memoized_method
  def _registered_language_aliases(self):
    return self.get_options().target_types

  @memoized_method
  def _target_type_for_language(self, language):
    alias_for_lang = self._registered_language_aliases()[language]
    registered_aliases = self.context.build_file_parser.registered_aliases()
    target_types = registered_aliases.target_types_by_alias.get(alias_for_lang, None)
    if not target_types:
      raise TaskError('Registered target type `{0}` for language `{1}` does not exist!'.format(alias_for_lang, language))
    if len(target_types) > 1:
      raise TaskError('More than one target type registered for language `{0}`'.format(language))
    return next(iter(target_types))

  def execute_codegen(self, target, target_workdir):
    self._validate_compiler_configs([target])
    self._must_have_sources(target)

    def compiler_args_has_rpc_style(compiler_args):
      return "--finagle" in compiler_args or "--ostrich" in compiler_args

    def merge_rpc_style_with_compiler_args(compiler_args, rpc_style):
      new_compiler_args = list(compiler_args)
      # ignore rpc_style if we think compiler_args is setting it
      if not compiler_args_has_rpc_style(compiler_args):
        if rpc_style == 'ostrich':
          new_compiler_args.append('--finagle')
          new_compiler_args.append('--ostrich')
        elif rpc_style == 'finagle':
          new_compiler_args.append('--finagle')
      return new_compiler_args

    namespace_map = self._thrift_defaults.namespace_map(target)
    compiler_args = merge_rpc_style_with_compiler_args(
        self._thrift_defaults.compiler_args(target), 
        self._validate_rpc_style(target))

    partial_cmd = self.PartialCmd(
        language=self._validate_language(target),
        namespace_map=tuple(sorted(namespace_map.items())) if namespace_map else (),
        default_java_namespace=self._thrift_defaults.default_java_namespace(target),
        include_paths=target.include_paths,
        compiler_args=compiler_args)

    self.gen(partial_cmd, target, target_workdir)

  def gen(self, partial_cmd, target, target_workdir):
    import_paths, _ = calculate_compile_sources([target], self.is_gentarget)

    args = list(partial_cmd.compiler_args)

    if partial_cmd.default_java_namespace:
      args.extend(['--default-java-namespace', partial_cmd.default_java_namespace])

    for import_path in import_paths:
      args.extend(['--import-path', import_path])

    args.extend(['--language', partial_cmd.language])

    for lhs, rhs in partial_cmd.namespace_map:
      args.extend(['--namespace-map', '%s=%s' % (lhs, rhs)])

    args.extend(['--dest', target_workdir])

    if not self.get_options().strict:
      args.append('--disable-strict')

    if partial_cmd.include_paths:
      for include_path in partial_cmd.include_paths:
        args.extend(['--include-path', include_path])

    if self.get_options().verbose:
      args.append('--verbose')

    gen_file_map_path = os.path.relpath(self._tempname())
    args.extend(['--gen-file-map', gen_file_map_path])

    args.extend(target.sources_relative_to_buildroot())

    classpath = self.tool_classpath('scrooge-gen')
    jvm_options = list(self.get_options().jvm_options)
    jvm_options.append('-Dfile.encoding=UTF-8')
    returncode = self.runjava(classpath=classpath,
                              main='com.twitter.scrooge.Main',
                              jvm_options=jvm_options,
                              args=args,
                              workunit_name='scrooge-gen')
    if 0 != returncode:
      raise TaskError('Scrooge compiler exited non-zero for {} ({})'.format(target, returncode))

  @staticmethod
  def _declares_exception(source):
    # ideally we'd use more sophisticated parsing
    exception_parser = re.compile(r'^\s*exception\s+(?:[^\s{]+)')
    return ScroogeGen._has_declaration(source, exception_parser)

  @staticmethod
  def _declares_service(source):
    # ideally we'd use more sophisticated parsing
    service_parser = re.compile(r'^\s*service\s+(?:[^\s{]+)')
    return ScroogeGen._has_declaration(source, service_parser)

  @staticmethod
  def _has_declaration(source, regex):
    source_path = os.path.join(get_buildroot(), source)
    with open(source_path) as thrift:
      return any(line for line in thrift if regex.search(line))

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
    return self._thrift_defaults.compiler(target) == 'scrooge'

  def _validate_compiler_configs(self, targets):
    assert len(targets) == 1, ("TODO: This method now only ever receives one target. Simplify.")
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

  def _must_have_sources(self, target):
    if isinstance(target, JavaThriftLibrary) and not target.payload.sources.source_paths:
      raise TargetDefinitionException(target, 'no thrift files found')

  def synthetic_target_type(self, target):
    language = self._thrift_defaults.language(target)
    return self._target_type_for_language(language)

  def synthetic_target_extra_dependencies(self, target, target_workdir):
    deps = OrderedSet(self._thrift_dependencies_for_target(target))
    deps.update(target.dependencies)
    return deps

  def synthetic_target_extra_exports(self, target, target_workdir):
    dep_info = self._resolved_export_info
    target_declares_service = any(self._declares_service(source)
                                  for source in target.sources_relative_to_buildroot())
    language = self._thrift_defaults.language(target)

    if target_declares_service:
      return dep_info.service[language]
    else:
      return dep_info.structs[language]

  def _thrift_dependencies_for_target(self, target):
    dep_info = self._resolved_dep_info
    target_declares_service_or_exception = any(self._declares_service(source) or self._declares_exception(source)
                                               for source in target.sources_relative_to_buildroot())
    language = self._thrift_defaults.language(target)

    if target_declares_service_or_exception:
      return dep_info.service[language]
    else:
      return dep_info.structs[language]

  @memoized_property
  def _resolved_dep_info(self):
    return ScroogeGen.DepInfo(self._resolve_deps(self.get_options().service_deps),
                              self._resolve_deps(self.get_options().structs_deps))

  @memoized_property
  def _resolved_export_info(self):
    return ScroogeGen.DepInfo(self._resolve_deps(self.get_options().service_exports),
                              self._resolve_deps(self.get_options().structs_exports))

  @property
  def _copy_target_attributes(self):
    return ['provides', 'strict_deps', 'fatal_warnings']
