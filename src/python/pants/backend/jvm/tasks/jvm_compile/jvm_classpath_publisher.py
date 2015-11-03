# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import os
from hashlib import sha1

from pants.backend.core.tasks.task import Task
from pants.util.dirutil import safe_mkdir, safe_rmtree


logger = logging.getLogger(__name__)


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
    """
    :type runtime_classpath: :class:`pants.backend.jvm.tasks.classpath_products.ClasspathProducts`
    """
    for target in self.context.targets():
      folder_for_symlinks = self._stable_output_folder(target)
      safe_rmtree(folder_for_symlinks)

      classpath_entries_for_target = \
        runtime_classpath.get_internal_classpath_entries_for_targets([target], transitive=False)

      if len(classpath_entries_for_target) > 0:
        safe_mkdir(folder_for_symlinks)

      for conf, entry in classpath_entries_for_target:
        file_name = os.path.basename(entry.path)
        symlink_name = '{}-{}'.format(sha1(entry.path).hexdigest(), file_name)
        os.symlink(entry.path, os.path.join(folder_for_symlinks, symlink_name))
