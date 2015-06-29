# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.core.tasks.task import Task
from pants.backend.jvm.subsystems.jvm import JVM
from pants.backend.jvm.tasks.classpath_util import ClasspathUtil


class JvmTask(Task):

  @classmethod
  def _legacy_dest_prefix(cls):
    return cls.options_scope.replace('.', '_')

  @classmethod
  def task_subsystems(cls):
    return super(JvmTask, cls).task_subsystems() + (JVM, )

  @classmethod
  def register_options(cls, register):
    super(JvmTask, cls).register_options(register)
    register('--confs', action='append', default=['default'],
             help='Use only these Ivy configurations of external deps.')

  @classmethod
  def prepare(cls, options, round_manager):
    round_manager.require_data('compile_classpath')

  def __init__(self, *args, **kwargs):
    super(JvmTask, self).__init__(*args, **kwargs)
    self.jvm = JVM.instance_for_task(self)
    self.jvm_options = self.jvm.get_jvm_options()
    self.args = self.jvm.get_program_args()
    self.confs = self.get_options().confs

  def classpath(self, targets, cp=None):
    classpath = list(cp) if cp else []

    classpath_for_targets = ClasspathUtil.classpath_entries(
      targets, self.context.products.get_data('compile_classpath'), self.confs)
    classpath.extend(classpath_for_targets)
    return classpath
