# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import os
import re

from pants.backend.codegen.antlr.java.java_antlr_library import JavaAntlrLibrary
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.backend.jvm.tasks.nailgun_task import NailgunTask
from pants.base.exceptions import TaskError
from pants.java.jar.jar_dependency import JarDependency
from pants.task.simple_codegen_task import SimpleCodegenTask
from pants.util.dirutil import safe_mkdir, safe_walk
from pants.util.memo import memoized_method


logger = logging.getLogger(__name__)


def antlr4_jar(name):
  return JarDependency(org='org.antlr', name=name, rev='4.1')


_DEFAULT_ANTLR_DEPS = {
  'antlr3': ('//:antlr-3.4', [JarDependency(org='org.antlr', name='antlr', rev='3.4')]),
  'antlr4': ('//:antlr-4', [antlr4_jar(name='antlr4'),
                            antlr4_jar(name='antlr4-runtime')])
}


# TODO: Refactor this and AntlrPyGen to share a common base class with most of the functionality.
# See comments there for what that would take.
class AntlrJavaGen(SimpleCodegenTask, NailgunTask):
  """Generate .java source code from ANTLR grammar files."""
  gentarget_type = JavaAntlrLibrary

  class AmbiguousPackageError(TaskError):
    """Raised when a java package cannot be unambiguously determined for a JavaAntlrLibrary."""

  # TODO: Do we need this?
  def find_sources(self, target, target_dir):
    sources = super(AntlrJavaGen, self).find_sources(target, target_dir)
    return [source for source in sources if source.endswith('.java')]

  @classmethod
  def register_options(cls, register):
    super(AntlrJavaGen, cls).register_options(register)
    for key, (classpath_spec, classpath) in _DEFAULT_ANTLR_DEPS.items():
      cls.register_jvm_tool(register, key, classpath=classpath, classpath_spec=classpath_spec)

  def is_gentarget(self, target):
    return isinstance(target, JavaAntlrLibrary)

  def synthetic_target_type(self, target):
    return JavaLibrary

  def execute_codegen(self, target, target_workdir):
    args = ['-o', target_workdir]
    compiler = target.compiler
    if target.package is None:
      java_package = self._get_sources_package(target)
    else:
      java_package = target.package

    if compiler == 'antlr3':
      if target.package is not None:
        logger.warn("The 'package' attribute is not supported for antlr3 and will be ignored.")
      java_main = 'org.antlr.Tool'
    elif compiler == 'antlr4':
      args.append('-visitor')  # Generate Parse Tree Visitor As Well
      # Note that this assumes that there is no package set in the antlr file itself,
      # which is considered an ANTLR best practice.
      args.append('-package')
      args.append(java_package)
      java_main = 'org.antlr.v4.Tool'
    else:
      raise TaskError('Unsupported ANTLR compiler: {}'.format(compiler))

    antlr_classpath = self.tool_classpath(compiler)
    sources = self._calculate_sources([target])
    args.extend(sources)
    result = self.runjava(classpath=antlr_classpath, main=java_main, args=args,
                          workunit_name='antlr')
    if result != 0:
      raise TaskError('java {} ... exited non-zero ({})'.format(java_main, result))

    self._rearrange_output_for_package(target_workdir, java_package)
    if compiler == 'antlr3':
      self._scrub_generated_timestamps(target_workdir)

  def synthetic_target_extra_dependencies(self, target, target_workdir):
    # Fetch the right java dependency from the target's compiler option
    return self._deps(target.compiler)

  @memoized_method
  def _deps(self, compiler):
    spec = self.get_options()[compiler]
    return list(self.resolve_deps([spec])) if spec else []

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

    def collect_sources(tgt):
      if self.is_gentarget(tgt):
        sources.update(tgt.sources_relative_to_buildroot())
    for target in targets:
      target.walk(collect_sources)
    return sources

  _COMMENT_WITH_TIMESTAMP_RE = re.compile('^//.*\d\d\d\d-\d\d-\d\d \d\d:\d\d:\d\d')

  def _rearrange_output_for_package(self, target_workdir, java_package):
    """Rearrange the output files to match a standard Java structure.

    Antlr emits a directory structure based on the relative path provided
    for the grammar file. If the source root of the file is different from
    the Pants build root, then the Java files end up with undesired parent
    directories.
    """
    package_dir_rel = java_package.replace('.', os.path.sep)
    package_dir = os.path.join(target_workdir, package_dir_rel)
    safe_mkdir(package_dir)
    for root, dirs, files in safe_walk(target_workdir):
      if root == package_dir_rel:
        # This path is already in the correct location
        continue
      for f in files:
        os.rename(
          os.path.join(root, f),
          os.path.join(package_dir, f)
        )

    # Remove any empty directories that were left behind
    for root, dirs, files in safe_walk(target_workdir, topdown = False):
      for d in dirs:
        full_dir = os.path.join(root, d)
        if not os.listdir(full_dir):
          os.rmdir(full_dir)

  def _scrub_generated_timestamps(self, target_workdir):
    """Remove the first line of comment from each file if it contains a timestamp."""
    for root, _, filenames in safe_walk(target_workdir):
      for filename in filenames:
        source = os.path.join(root, filename)

        with open(source) as f:
          lines = f.readlines()
        if len(lines) < 1:
          return
        with open(source, 'w') as f:
          if not self._COMMENT_WITH_TIMESTAMP_RE.match(lines[0]):
            f.write(lines[0])
          for line in lines[1:]:
            f.write(line)
