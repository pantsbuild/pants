# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.jvm.tasks.classpath_util import ClasspathUtil
from pants.task.task import Task


class RuntimeClasspathPublisher(Task):
  """Create stable symlinks for runtime classpath entries for JVM targets."""

  @classmethod
  def register_options(cls, register):
    super(Task, cls).register_options(register)
    register('--use-old-naming-style', advanced=True, default=True, action='store_true',
             deprecated_version='0.0.65',
             deprecated_hint='Switch to use the safe identifier to construct canonical classpath.',
             help='Use the old (unsafe) naming style construct canonical classpath.')

  @classmethod
  def prepare(cls, options, round_manager):
    round_manager.require_data('runtime_classpath')

  @property
  def _output_folder(self):
    return self.options_scope.replace('.', os.sep)

  def execute(self):
    basedir = os.path.join(self.get_options().pants_distdir, self._output_folder)
    runtime_classpath = self.context.products.get_data('runtime_classpath')
    use_target_id = not self.get_options().use_old_naming_style
    ClasspathUtil.create_canonical_classpath(runtime_classpath,
                                             self.context.targets(),
                                             basedir,
                                             save_classpath_file=True,
                                             use_target_id=use_target_id)
