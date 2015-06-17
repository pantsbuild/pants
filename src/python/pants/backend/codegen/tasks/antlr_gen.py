# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import os
import re

from twitter.common.collections import OrderedSet

from pants.backend.codegen.targets.java_antlr_library import JavaAntlrLibrary
from pants.backend.codegen.tasks.code_gen import CodeGen
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.backend.jvm.tasks.nailgun_task import NailgunTask
from pants.base.address import SyntheticAddress
from pants.base.address_lookup_error import AddressLookupError
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.util.dirutil import safe_mkdir


logger = logging.getLogger(__name__)


class AntlrGen(CodeGen, NailgunTask):

  class AmbiguousPackageError(TaskError):
    """Raised when a java package cannot be unambiguously determined for a JavaAntlrLibrary."""

  @classmethod
  def register_options(cls, register):
    super(AntlrGen, cls).register_options(register)
    cls.register_jvm_tool(register, 'antlr3', ['//:antlr-3.4'])
    cls.register_jvm_tool(register, 'antlr4', ['//:antlr-4'])

  @property
  def config_section(self):
    return 'antlr'

  def is_gentarget(self, target):
    return isinstance(target, JavaAntlrLibrary)

  def is_forced(self, lang):
    return lang == 'java'

  def genlangs(self):
    return dict(java=lambda t: t.is_jvm)

  def genlang(self, lang, targets):
    if lang != 'java':
      raise TaskError('Unrecognized antlr gen lang: {}'.format(lang))

    # TODO: Instead of running the compiler for each target, collect the targets
    # by type and invoke it twice, once for antlr3 and once for antlr4.

    for target in targets:
      java_out = self._java_out(target)
      safe_mkdir(java_out)

      args = ['-o', java_out]

      if target.compiler == 'antlr3':
        antlr_classpath = self.tool_classpath('antlr3')
        if target.package is not None:
          logger.warn("The 'package' attribute is not supported for antlr3 and will be ignored.")
        java_main = 'org.antlr.Tool'
      elif target.compiler == 'antlr4':
        antlr_classpath = self.tool_classpath('antlr4')
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
        raise TaskError('java {} ... exited non-zero ({})'.format(java_main, result))

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
      raise TaskError('Unrecognized antlr gen lang: {}'.format(lang))
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

    syn_target_sourceroot = os.path.join(self._java_out(target), target.target_base)

    # Removes timestamps in generated source to get stable fingerprint for buildcache.
    for source in generated_sources:
      self._scrub_generated_timestamp(os.path.join(syn_target_sourceroot, source))

    # The runtime deps are the same JAR files as those of the tool used to compile.
    # TODO: In antlr4 there is a separate runtime-only JAR, so use that.
    deps = self._resolve_java_deps(target)

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

  _COMMENT_WITH_TIMESTAMP_RE = re.compile('^//.*\d\d\d\d-\d\d-\d\d \d\d:\d\d:\d\d')
  def _scrub_generated_timestamp(self, source):
    lines = None
    with open(source) as f:
      lines = f.readlines()
    with open(source, 'w') as f:
      for line in lines:
        if not self._COMMENT_WITH_TIMESTAMP_RE.match(line):
          f.write(line)

  def _resolve_java_deps(self, target):
    dep_specs = self.get_options()[target.compiler]

    deps = OrderedSet()
    try:
      for dep in dep_specs:
        deps.update(self.context.resolve(dep))
      return deps
    except AddressLookupError as e:
      raise self.DepLookupError('{message}\n'
                                '  referenced from option {option} in scope {scope}'
                                .format(message=e, option=target.compiler,
                                        scope=self.options_scope))

  def _java_out(self, target):
    return os.path.join(self.workdir, target.compiler, 'gen-java')
