# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from collections import defaultdict, namedtuple
import logging
import os

from twitter.common.collections import OrderedSet

from pants.backend.codegen.targets.java_antlr_library import JavaAntlrLibrary
from pants.backend.codegen.tasks.code_gen import CodeGen
from pants.backend.jvm.targets.jar_dependency import JarDependency
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.backend.jvm.tasks.jvm_tool_task_mixin import JvmToolTaskMixin
from pants.backend.jvm.tasks.nailgun_task import NailgunTask
from pants.base.address import SyntheticAddress
from pants.base.address_lookup_error import AddressLookupError
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.util.dirutil import safe_mkdir


logger = logging.getLogger(__name__)


class AntlrGen(CodeGen, NailgunTask, JvmToolTaskMixin):

  class AmbiguousPackageError(TaskError):
    """Raised when a java package cannot be unambiguously determined for a JavaAntlrLibrary."""

  class UnsupportedCompilerError(TaskError):
    """Raised when an un-recognized antlr compiler is specified for a JavaAntlrLibrary."""

  # Maps the compiler attribute of a target to the config key in pants.ini
  class ToolConfig(namedtuple('AntlrConfig', ['section', 'default_deps'])):
    @property
    def key(self):
      return 'javadeps'

    def get_deps(self, context, workdir):
      deps = context.config.getlist(self.section, self.key, default=None)
      if deps is None:
        spec_path = '{workdir}/3rdparty/{section}'.format(workdir=workdir, section=self.section)
        spec_relpath = os.path.relpath(spec_path, get_buildroot())
        default_deps_addr = SyntheticAddress.parse('{spec_relpath}:tool-deps'
                                                   .format(spec_relpath=spec_relpath,
                                                           section=self.section))
        if not context.build_graph.get_target(default_deps_addr):
          context.add_new_target(default_deps_addr, JarLibrary, jars=self.default_deps)
        deps = [default_deps_addr.spec]
      return deps

  # TODO(John Sirois): seperate the compiler deps from the runtime deps and apply these exactly
  # where needed.
  _TOOL_CONFIG_BY_COMPILER = {
    'antlr3': ToolConfig(section='antlr-gen',
                         default_deps=[JarDependency('org.antlr', 'antlr', '3.4')]),
    'antlr4': ToolConfig(section='antlr4-gen',
                         default_deps=[JarDependency('org.antlr', 'antlr4', '4.3'),
                                       JarDependency('org.antlr', 'antlr4-runtime', '4.3')]),
  }

  @classmethod
  def get_tool_config(cls, compiler):
    return cls._TOOL_CONFIG_BY_COMPILER.get(compiler)

  @classmethod
  def get_compiler(cls, target):
    return target.compiler or 'antlr3'

  _GENERIC_CONFIG_SECTION = 'antlr'

  def __init__(self, *args, **kwargs):
    super(AntlrGen, self).__init__(*args, **kwargs)

    invalid_compilers = defaultdict(list)
    active_compilers = set()
    for target in self.context.targets(predicate=self.is_gentarget):
      if target.compiler and target.compiler not in self._TOOL_CONFIG_BY_COMPILER:
        invalid_compilers[target.compiler].append(target)
      else:
        active_compilers.add(self.get_compiler(target))

    if invalid_compilers:
      invalid_items = []
      for compiler, targets in invalid_compilers.items():
        addresses = '\n\t'.join(sorted(str(t.address) for t in targets))
        invalid_items.append('- {compiler!r} by:\n\t{addresses}'
                             .format(compiler=compiler, addresses=addresses))
      raise self.UnsupportedCompilerError('Unsupported antlr compilers specified:\n{0}'
                                          .format('\n'.join(invalid_items)))

    for compiler in active_compilers:
      # TODO(John Sirois): generify this mechanism in the JvmToolTaskMixin itself for all
      # such Tasks to leverage.
      tool_config = self.get_tool_config(compiler)
      deps = tool_config.get_deps(self.context, self.workdir)
      self.register_jvm_tool(key=compiler, target_addrs=deps, ini_section=tool_config.section,
                             ini_key=tool_config.key)

  @property
  def config_section(self):
    return self._GENERIC_CONFIG_SECTION

  def is_gentarget(self, target):
    return isinstance(target, JavaAntlrLibrary)

  def is_forced(self, lang):
    return lang == 'java'

  def genlangs(self):
    return dict(java=lambda t: t.is_jvm)

  def genlang(self, lang, targets):
    if lang != 'java':
      raise TaskError('Unrecognized antlr gen lang: %s' % lang)

    # TODO: Instead of running the compiler for each target, collect the targets
    # by type and invoke it twice, once for antlr3 and once for antlr4.

    for target in targets:
      java_out = self._java_out(target)
      safe_mkdir(java_out)

      compiler = self.get_compiler(target)
      antlr_classpath = self.tool_classpath(compiler)
      args = ["-o", java_out]

      if compiler == 'antlr3':
        if target.package is not None:
          logger.warn("The 'package' attribute is not supported for antlr3 and will be ignored.")
        java_main = 'org.antlr.Tool'
      elif compiler == 'antlr4':
        args.append('-visitor')  # Generate Parse Tree Visitor As Well
        # Note that this assumes that there is no package set in the antlr file itself,
        # which is considered an ANTLR best practice.
        args.append('-package')
        if target.package is None:
          args.append(self._get_sources_package(target))
        else:
          args.append(target.package)
        java_main = 'org.antlr.v4.Tool'
      else:
        # Can't happen due to __init__ check.
        raise self.UnsupportedCompilerError('Unknown ANTLR compiler: {}'.format(compiler))

      sources = self._calculate_sources([target])
      args.extend(sources)

      result = self.runjava(classpath=antlr_classpath, main=java_main,
                            args=args, workunit_name='antlr')
      if result != 0:
        raise TaskError('java %s ... exited non-zero (%i)' % (java_main, result))

  # This checks to make sure that all of the sources have an identical package source structure, and
  # if they do, uses that as the package. If they are different, then the user will need to set the
  # package as it cannot be correctly inferred.
  def _get_sources_package(self, target):
    parents = set([os.path.dirname(source) for source in target.sources_relative_to_source_root()])
    if len(parents) != 1:
      raise self.AmbiguousPackageError('Antlr sources in multiple directories, cannot infer '
                                       'package. Please set package member in antlr target.')
    return parents.pop().replace('/', '.')

  def _calculate_sources(self, targets):
    sources = set()

    def collect_sources(target):
      if self.is_gentarget(target):
        sources.update(target.sources_relative_to_buildroot())
    for target in targets:
      target.walk(collect_sources)
    return sources

  def createtarget(self, lang, gentarget, dependees):
    if lang != 'java':
      raise TaskError('Unrecognized antlr gen lang: %s' % lang)
    return self._create_java_target(gentarget, dependees)

  def _create_java_target(self, target, dependees):
    antlr_files_suffix = ["Lexer.java", "Parser.java"]
    if self.get_compiler(target) == 'antlr4':
      antlr_files_suffix = ["BaseListener.java", "BaseVisitor.java",
                            "Listener.java", "Visitor.java"] + antlr_files_suffix

    generated_sources = []
    for source in target.sources_relative_to_source_root():
      # Antlr enforces that generated sources are relative to the base filename, and that
      # each grammar filename must match the resulting grammar Lexer and Parser classes.
      source_base, source_ext = os.path.splitext(source)
      for suffix in antlr_files_suffix:
        generated_sources.append(source_base + suffix)

    deps = self._resolve_java_deps(target)

    syn_target_sourceroot = os.path.join(self._java_out(target), target.target_base)
    spec_path = os.path.relpath(syn_target_sourceroot, get_buildroot())
    address = SyntheticAddress(spec_path=spec_path, target_name=target.id)
    tgt = self.context.add_new_target(address,
                                      JavaLibrary,
                                      dependencies=deps,
                                      derived_from=target,
                                      sources=generated_sources,
                                      provides=target.provides,
                                      excludes=target.excludes)
    for dependee in dependees:
      dependee.inject_dependency(tgt.address)
    return tgt

  def _resolve_java_deps(self, target):
    tool_config = self.get_tool_config(self.get_compiler(target))

    deps = OrderedSet()
    try:
      for dep in tool_config.get_deps(self.context, self.workdir):
        deps.update(self.context.resolve(dep))
      return deps
    except AddressLookupError as e:
      raise self.DepLookupError("{message}\n"
                                "  referenced from [{section}] key: {key} in pants.ini"
                                .format(message=e, section=tool_config.section,
                                        key=tool_config.key))

  def _java_out(self, target):
    return os.path.join(self.workdir, self.get_compiler(target), 'gen-java')
