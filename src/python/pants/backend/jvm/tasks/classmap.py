# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.task.console_task import ConsoleTask

class ClassmapTask(ConsoleTask):
  """Print a mapping from class name to the owning target from compile classpath."""

  @classmethod
  def register_options(cls, register):
    super(ClassmapTask, cls).register_options(register)

  def _get_class_target_map(self):
    compile_classpath = self.context.products.get_data('compile_classpath')
    classpath_product = self.context.products.get_data('runtime_classpath', compile_classpath.copy)
    classes_by_source = self.context.products.get_data('classes_by_source')
    product_deps_by_src = self.context.products.get_data('product_deps_by_src')
    return None

  def console_output(self, _):
    self._get_class_target_map()
    visited = set()
    for target in self.determine_target_roots('classmap'):
      if target not in visited:
        visited.add(target)
        for rel_source in target.sources_relative_to_buildroot():
          yield '{} {}'.format(rel_source, target.address.spec)

  @classmethod
  def prepare(cls, options, round_manager):
    super(ClassmapTask, cls).prepare(options, round_manager)
    round_manager.require_data('classes_by_source')
    round_manager.require_data('compile_classpath')
    round_manager.require_data('product_deps_by_src')
