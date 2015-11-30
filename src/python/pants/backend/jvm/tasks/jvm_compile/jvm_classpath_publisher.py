# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.task.task import Task
from pants.util.dirutil import safe_mkdir, safe_open, safe_rmtree


class RuntimeClasspathPublisher(Task):
  """Creates symlinks in pants_distdir to classpath entries per target."""

  @classmethod
  def prepare(cls, options, round_manager):
    round_manager.require_data('runtime_classpath')

  @property
  def _output_folder(self):
    return self.options_scope.replace('.', os.sep)

  def _stable_output_folder(self, target):
    """
    :type target: pants.build_graph.target.Target
    """
    address = target.address
    return os.path.join(
      self.get_options().pants_distdir,
      self._output_folder,
      # target.address.spec is used in export goal to identify targets
      address.spec.replace(':', os.sep) if address.spec_path else address.target_name,
    )

  def execute(self):
    runtime_classpath = self.context.products.get_data('runtime_classpath')
    for target in self.context.targets():
      folder_for_symlinks = self._stable_output_folder(target)
      safe_rmtree(folder_for_symlinks)

      classpath_entries_for_target = runtime_classpath.get_internal_classpath_entries_for_targets(
        [target])

      if len(classpath_entries_for_target) > 0:
        safe_mkdir(folder_for_symlinks)

        classpath = []
        for (index, (conf, entry)) in enumerate(classpath_entries_for_target):
          classpath.append(entry.path)
          file_name = os.path.basename(entry.path)
          # Avoid name collisions
          symlink_name = '{}-{}'.format(index, file_name)
          os.symlink(entry.path, os.path.join(folder_for_symlinks, symlink_name))

        with safe_open(os.path.join(folder_for_symlinks, 'classpath.txt'), 'w') as classpath_file:
          classpath_file.write(os.pathsep.join(classpath))
          classpath_file.write('\n')
