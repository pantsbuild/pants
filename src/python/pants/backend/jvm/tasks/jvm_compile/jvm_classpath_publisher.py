# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import os

from pants.backend.core.tasks.task import Task
from pants.util.dirutil import safe_mkdir


logger = logging.getLogger(__name__)


class CompileClasspathPublisher(Task):
  @classmethod
  def prepare(cls, options, round_manager):
    round_manager.require_data('runtime_classpath')

  def _stabel_output_folder(self, target):
    """
    :type target: pants.build_graph.target.Target
    """
    return os.path.join(
      self.get_options().pants_distdir,
      'runtime_classpath',
      target.address.path_safe_spec
    )

  def execute(self):
    runtime_classpath = self.context.products.get_data('runtime_classpath')
    """
    :type runtime_classpath: pants.backend.jvm.tasks.classpath_products.ClasspathProducts
    """
    for target in self.context.targets():
      """
      :type target: pants.build_graph.target.Target
      """
      classpath_entries_for_target = runtime_classpath.get_for_target(target, transitive=False)
      for (conf, path) in classpath_entries_for_target:
        if os.path.basename(path) == 'z.jar':
          symlink = self._stabel_output_folder(target)
          safe_mkdir(symlink, clean=True)
          os.symlink(path, os.path.join(symlink, "classes.jar"))
