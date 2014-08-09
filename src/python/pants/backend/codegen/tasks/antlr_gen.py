# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os

from twitter.common.collections import OrderedSet

from pants.backend.codegen.targets.java_antlr_library import JavaAntlrLibrary
from pants.backend.codegen.tasks.code_gen import CodeGen
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.backend.jvm.tasks.jvm_tool_task_mixin import JvmToolTaskMixin
from pants.backend.jvm.tasks.nailgun_task import NailgunTask
from pants.base.address import SyntheticAddress
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.util.dirutil import safe_mkdir


class AntlrGen(CodeGen, NailgunTask, JvmToolTaskMixin):

  # Maps the compiler attribute of a target to the config key in pants.ini
  _CONFIG_SECTION_BY_COMPILER = {
    'antlr3': 'antlr-gen',
    'antlr4': 'antlr4-gen',
  }

  _GENERIC_CONFIG_SECTION = 'antlr'

  def __init__(self, *args, **kwargs):
    super(AntlrGen, self).__init__(*args, **kwargs)

    # TODO(John Sirois): kill if not needed by prepare_gen
    self._classpath_by_compiler = {}

    active_compilers = set(map(lambda t: t.compiler,
                               self.context.targets(predicate=self.is_gentarget)))
    for compiler, tools in self._all_possible_antlr_bootstrap_tools():
      if compiler in active_compilers:
        self.register_jvm_tool(compiler, tools)

  @property
  def config_section(self):
    return self._GENERIC_CONFIG_SECTION

  def is_gentarget(self, target):
    return isinstance(target, JavaAntlrLibrary)

  def is_forced(self, lang):
    return lang == 'java'

  def genlangs(self):
    return dict(java=lambda t: t.is_jvm)

  def prepare_gen(self, targets):
    compilers = set(map(lambda t: t.compiler, targets))
    for compiler in compilers:
      classpath = self.tool_classpath(compiler)
      self._classpath_by_compiler[compiler] = classpath

  def genlang(self, lang, targets):
    if lang != 'java':
      raise TaskError('Unrecognized antlr gen lang: %s' % lang)

    # TODO: Instead of running the compiler for each target, collect the targets
    # by type and invoke it twice, once for antlr3 and once for antlr4.

    for target in targets:
      java_out = self._java_out(target)
      safe_mkdir(java_out)

      antlr_classpath = self._classpath_by_compiler[target.compiler]
      args = ["-o", java_out]

      if target.compiler == 'antlr3':
        java_main = 'org.antlr.Tool'
      elif target.compiler == 'antlr4':
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
        raise TaskError('Unknown ANTLR compiler: {}'.format(target.compiler))

      sources = self._calculate_sources([target])
      args.extend(sources)

      result = self.runjava(classpath=antlr_classpath, main=java_main,
                            args=args, workunit_name='antlr')
      if result != 0:
        raise TaskError('java %s ... exited non-zero (%i)' % (java_main, result))

  # This checks to make sure that all of the sources have an identical package source structure, and if
  # they do, uses that as the package. If they are different, then the user will need to set the package
  # as it cannot be correctly inferred.
  def _get_sources_package(self, target):
    parents = set([os.path.dirname(source) for source in target.sources])
    if len(parents) != 1:
      raise TaskError('Antlr sources in multiple directories, cannot infer package.'
                      'Please set package member in antlr target.')
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
    if target.compiler == 'antlr4':
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
    key = self._CONFIG_SECTION_BY_COMPILER[target.compiler]

    deps = OrderedSet()
    for dep in self.context.config.getlist(key, 'javadeps'):
      deps.update(self.context.resolve(dep))
    return deps

  def _all_possible_antlr_bootstrap_tools(self):
    for compiler, key in self._CONFIG_SECTION_BY_COMPILER.items():
      yield compiler, self.context.config.getlist(key, 'javadeps')

  def _java_out(self, target):
    return os.path.join(self.workdir, target.compiler, 'gen-java')
