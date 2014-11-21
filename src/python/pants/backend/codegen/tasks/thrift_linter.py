# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnit
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
  def register_options(cls, register):
    super(ThriftLinter, cls).register_options(register)
    register('--strict', default=None, action='store_true',
             help='Fail the goal if thrift linter errors are found.')

  @classmethod
  def product_types(cls):
    # Declare the product of this goal. Gen depends on thrift-linter.
    return ['thrift-linter']

  def __init__(self, *args, **kwargs):
    super(ThriftLinter, self).__init__(*args, **kwargs)

    self._bootstrap_key = 'scrooge-linter'
    self.register_jvm_tool_from_config(self._bootstrap_key, self.context.config,
                                       self._CONFIG_SECTION, 'bootstrap-tools',
                                       default=['//:scrooge-linter'])

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
    # TODO: the new options parsing doesn't support this. This task wants the target in the BUILD
    # file to be able to override a value in the pants.ini file. Finally, command-line overrides
    # that. But parsing of options combines the command-line values and pants.ini values in a single
    # "merged" view, into which there's no opportunity to inject an override from the BUILD target.

    # The strict value is read from the following, in order:
    # 1. command line, --[no-]thrift-linter-strict
    # 2. java_thrift_library target in BUILD file, thrift_linter_strict = False,
    # 3. pants.ini, [scrooge-linter] section, strict field.
    # 4. default = False
    cmdline_strict = self.get_options().strict

    if cmdline_strict is not None:
      return self._to_bool(cmdline_strict)

    if target.thrift_linter_strict is not None:
      return self._to_bool(target.thrift_linter_strict)

    return self._to_bool(self.context.config.get(self._CONFIG_SECTION, 'strict',
                                                 default=ThriftLinter.STRICT_DEFAULT))

  def lint(self, target, path):
    self.context.log.debug('Linting %s' % path)

    classpath = self.tool_classpath(self._bootstrap_key)
    config_args = self.context.config.getlist(self._CONFIG_SECTION, 'linter_args', default=[])
    if not self.is_strict(target):
      config_args.append('--ignore-errors')

    args = config_args + [path]

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
