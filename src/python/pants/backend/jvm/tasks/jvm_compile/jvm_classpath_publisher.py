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
  def prepare(cls, options, round_manager):
    round_manager.require_data('runtime_classpath')

  @property
  def _output_folder(self):
    return self.options_scope.replace('.', os.sep)

  def execute(self):
    basedir = os.path.join(self.get_options().pants_distdir, self._output_folder)
    runtime_classpath = self.context.products.get_data('runtime_classpath')
    ClasspathUtil.create_canonical_classpath(runtime_classpath,
                                             self.context.targets(),
                                             basedir,
                                             save_classpath_file=True)
