# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import os

from pants.backend.core.tasks.task import Task
from pants.util.dirutil import safe_mkdir


logger = logging.getLogger(__name__)


class RuntimeClasspathPublisher(Task):
  """
  Creates symlinks in pants_distdir to context jars per target.

  See JvmCompile#_create_context_jar for details.
  """

  @classmethod
  def prepare(cls, options, round_manager):
    round_manager.require_data('runtime_classpath')

  def _stable_output_folder(self, target):
    """
    :type target: pants.build_graph.target.Target
    """
    return os.path.join(
      self.get_options().pants_distdir,
      self.options_scope.replace('.', os.sep),
      'runtime_classpath',
      # target.address.spec is used in export goal to identify targets
      target.address.spec.replace(':', os.sep),
    )

  def execute(self):
    runtime_classpath = self.context.products.get_data('runtime_classpath')
    """
    :type runtime_classpath: pants.backend.jvm.tasks.classpath_products.ClasspathProducts
    """
    for target in self.context.targets():
      folder_for_symlinks = self._stable_output_folder(target)
      safe_mkdir(folder_for_symlinks, clean=True)
      """
      :type target: pants.build_graph.target.Target
      """
      classpath_entries_for_target = \
        runtime_classpath.get_internal_classpath_entries_for_targets([target], transitive=False)
      for conf, entry in classpath_entries_for_target:
        path = entry.path
        os.symlink(path, os.path.join(folder_for_symlinks, os.path.basename(path)))
