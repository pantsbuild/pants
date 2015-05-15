# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.core.tasks.task import Task
from pants.backend.jvm.targets.jvm_target import JvmTarget
from pants.goal.products import UnionProducts

class ResolveExcludes(Task):

  @classmethod
  def register_options(cls, register):
    register('--skip', action='store_true', default=False,
             help='Skip collecting excludes.')

  @classmethod
  def product_types(cls):
    return ['compile_classpath_exclude_patterns']

  def execute(self):
    compile_classpath_excludes = self.context.products.get_data('compile_classpath_exclude_patterns',
                                                                lambda: UnionProducts())
    if self.get_options().skip:
      return

    targets = self.context.targets(lambda t: isinstance(t, JvmTarget))

    for target in targets:
      if target.excludes:
        compile_classpath_excludes.add_for_target(target,
                                                  [os.path.sep.join(['jars', e.org, e.name or ''])
                                                   for e in target.excludes])
