# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.backend.codegen.targets.java_thrift_library import JavaThriftLibrary

from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnit
from pants.backend.core.tasks.console_task import ConsoleTask
from pants.backend.jvm.tasks.jvm_tool_task_mixin import JvmToolTaskMixin
from pants.backend.jvm.tasks.nailgun_task import NailgunTask

class ThriftLinter(NailgunTask, JvmToolTaskMixin):
  """Print linter warnings for thrift files.
  """

  _CONFIG_SECTION = 'thrift-linter'

  STRICT_DEFAULT = False

  @staticmethod
  def _is_thrift(target):
    return target.is_thrift

  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    super(ThriftLinter, cls).setup_parser(option_group, args, mkflag)

    option_group.add_option(mkflag('strict'), mkflag('strict', negate=True),
                            dest='thrift_linter_strict',
                            default=None,
                            action='callback', callback=mkflag.set_bool,
                            help='[%default] Fail the goal if thrift errors are found.')

  @classmethod
  def product_types(cls):
    # Declare the product of this goal. Gen depends on thrift-linter.
    return ['thrift-linter']

  def __init__(self, *args, **kwargs):
    super(ThriftLinter, self).__init__(*args, **kwargs)

    self._bootstrap_key = 'scrooge-linter'

    bootstrap_tools = self.context.config.getlist(self._CONFIG_SECTION, 'bootstrap-tools',
                                                  default=['//:scrooge-linter'])
    self.register_jvm_tool(self._bootstrap_key, bootstrap_tools)

  @property
  def config_section(self):
    return self._CONFIG_SECTION

  def prepare(self, round_manager):
    # Linter depends on ivy running before it.
    round_manager.require_data('ivy_imports')

  def _to_bool(self, value):
    # Converts boolean and string values to boolean.
    return str(value) == 'True'

  def is_strict(self, target):
    # The strict value is read from the following, in order:
    # 1. command line, --[no-]thrift-linter-strict
    # 2. java_thrift_library target in BUILD file, thrift_linter_strict = False,
    # 3. pants.ini, [scrooge-linter] section, strict field.
    # 4. default = False
    cmdline_strict = self.context.options.thrift_linter_strict

    if cmdline_strict != None:
      return self._to_bool(cmdline_strict)

    if target.thrift_linter_strict != None:
      return self._to_bool(target.thrift_linter_strict)

    return self._to_bool(self.context.config.get(self._CONFIG_SECTION, 'strict',
                                                 default=ThriftLinter.STRICT_DEFAULT))

  def lint(self, target, path):
    self.context.log.debug('Linting %s' % path)

    classpath = self.tool_classpath(self._bootstrap_key)
    args = [path, '--verbose']
    if not self.is_strict(target):
      args.append('--ignore-errors')

    # If runjava returns non-zero, this marks the workunit as a
    # FAILURE, and there is no way to wrap this here.
    returncode = self.runjava(classpath=classpath,
                              main='com.twitter.scrooge.linter.Main',
                              args=args,
                              workunit_labels=[WorkUnit.COMPILER])  # to let stdout/err through.

    if returncode != 0:
      raise TaskError('Lint errors in %s.' % path)

  def execute(self):
    thrift_targets = self.context.targets(self._is_thrift)
    for target in thrift_targets:
      for path in target.sources_relative_to_buildroot():
        self.lint(target, path)
