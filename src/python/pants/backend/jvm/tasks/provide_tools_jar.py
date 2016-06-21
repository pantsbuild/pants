# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

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

  @property
  def create_target_dirs(self):
    # Create-but-don't-cache the target directories. The created symlinks are not portable.
    return True

  def execute(self):
    cp_init_func = ClasspathProducts.init_func(self.get_options().pants_workdir)
    compile_classpath = self.context.products.get_data('compile_classpath', init_func=cp_init_func)

    with self.invalidated(self.context.targets(is_tools_jar)) as invalidation_check:
      for vt in invalidation_check.all_vts:
        jar_path = self._jar_path(vt.results_dir)
        if not vt.valid:
          self._symlink_tools_jar(jar_path)
        compile_classpath.add_for_target(vt.target, [('default', jar_path)])

  @memoized_property
  def _tools_jar(self):
    self.set_distribution(jdk=True)
    jars = self.dist.find_libs(['tools.jar'])
    if len(jars) != 1:
      raise TaskError('Expected a single `tools.jar` entry for {}; got: {}'.format(
        self.dist, jars))
    return jars[0]

  def _jar_path(self, chroot):
    return os.path.join(chroot, 'tools.jar')

  def _symlink_tools_jar(self, dest_jar_path):
    relative_symlink(self._tools_jar, dest_jar_path)
