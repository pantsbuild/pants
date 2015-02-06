# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.core.tasks.task import Task
from pants.backend.jvm.jvm_debug_config import JvmDebugConfig
from pants.base.build_environment import get_buildroot
from pants.util.strutil import safe_shlex_split


class JvmTask(Task):

  @classmethod
  def _legacy_dest_prefix(cls):
    return cls.options_scope.replace('.', '_')

  @classmethod
  def register_options(cls, register):
    super(JvmTask, cls).register_options(register)
    register('--jvm-options', action='append', metavar='<option>...',
             help='Run the jvm with these extra jvm options.')
    register('--args', action='append', metavar='<arg>...',
             help='Run the jvm with these extra program args.')
    register('--debug', action='store_true',
             help='Run the jvm under a debugger.')
    register('--confs', action='append', default=['default'],
             help='Use only these Ivy configurations of external deps.')

  @classmethod
  def prepare(cls, options, round_manager):
    round_manager.require_data('compile_classpath')

  def __init__(self, *args, **kwargs):
    super(JvmTask, self).__init__(*args, **kwargs)

    self.jvm_options = []
    for jvm_option in self.get_options().jvm_options:
      self.jvm_options.extend(safe_shlex_split(jvm_option))

    if self.get_options().debug:
      self.jvm_options.extend(JvmDebugConfig.debug_args(self.context.config))

    self.args = []
    for arg in self.get_options().args:
      self.args.extend(safe_shlex_split(arg))

    self.confs = self.get_options().confs

  def classpath(self, cp=None, confs=None):
    classpath = list(cp) if cp else []

    compile_classpath = self.context.products.get_data('compile_classpath')
    classpath.extend(path for conf, path in compile_classpath if not confs or conf in confs)

    def add_resource_paths(predicate):
      bases = set()
      for target in self.context.targets():
        if predicate(target):
          if target.target_base not in bases:
            sibling_resources_base = os.path.join(os.path.dirname(target.target_base), 'resources')
            classpath.append(os.path.join(get_buildroot(), sibling_resources_base))
            bases.add(target.target_base)

    if self.context.config.getbool('jvm', 'parallel_src_paths', default=False):
      add_resource_paths(lambda t: t.is_jvm and not t.is_test)

    if self.context.config.getbool('jvm', 'parallel_test_paths', default=False):
      add_resource_paths(lambda t: t.is_jvm and t.is_test)

    return classpath
