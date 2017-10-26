# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.jvm.subsystems.java import Java
from pants.backend.jvm.targets.tools_jar import ToolsJar
from pants.backend.jvm.tasks.classpath_products import ClasspathProducts
from pants.backend.jvm.tasks.jvm_tool_task_mixin import JvmToolTaskMixin
from pants.base.exceptions import TaskError
from pants.util.dirutil import relative_symlink
from pants.util.memo import memoized_property


def is_tools_jar(target):
  return isinstance(target, ToolsJar)


class ProvideToolsJar(JvmToolTaskMixin):
  """Symlinks and adds the tools.jar as a classpath entry for ToolsJar targets."""

  @classmethod
  def product_types(cls):
    return ['compile_classpath']

  @classmethod
  def subsystem_dependencies(cls):
    return super(ProvideToolsJar, cls).subsystem_dependencies() + (Java,)

  @classmethod
  def implementation_version(cls):
    return super(ProvideToolsJar, cls).implementation_version() + [('ProvideToolsJar', 2)]

  @property
  def create_target_dirs(self):
    # Create-but-don't-cache the target directories. The created symlinks are not portable.
    return True

  def execute(self):
    cp_init_func = ClasspathProducts.init_func(self.get_options().pants_workdir)
    compile_classpath = self.context.products.get_data('compile_classpath', init_func=cp_init_func)

    with self.invalidated(self.context.targets(is_tools_jar)) as invalidation_check:
      for vt in invalidation_check.all_vts:
        tools_classpath = self._tools_classpath_pairs(vt.results_dir)
        if not vt.valid:
          self._symlink_tools_classpath(tools_classpath)
        compile_classpath.add_for_target(vt.target,
                                         [('default', entry) for _, entry in tools_classpath])

  def _tools_classpath_pairs(self, dest_dir):
    """Given a destination directory, returns a list of tuples of (src, dst) symlink pairs."""
    tools_classpath = self._tools_classpath
    return [(entry, os.path.join(dest_dir, '{}-{}'.format(idx, os.path.basename(entry))))
            for idx, entry in enumerate(tools_classpath)]

  @memoized_property
  def _tools_classpath(self):
    """Returns a classpath representing the (equivalent of the) `tools.jar`.

    If `javac` has been set explicitly, it is used. Otherwise, searches the current distribution.
    """

    javac_classpath = Java.global_javac_classpath(self.context.products)
    if javac_classpath:
      return javac_classpath

    self.set_distribution(jdk=True)
    jars = self.dist.find_libs(['tools.jar'])
    if len(jars) != 1:
      raise TaskError('Expected a single `tools.jar` entry for {}; got: {}'.format(
        self.dist, jars))
    return jars

  def _symlink_tools_classpath(self, tools_classpath):
    for src, dst in tools_classpath:
      relative_symlink(src, dst)
