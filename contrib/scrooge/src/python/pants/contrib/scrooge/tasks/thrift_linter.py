# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.jvm.tasks.jvm_tool_task_mixin import JvmToolTaskMixin
from pants.backend.jvm.tasks.nailgun_task import NailgunTask
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnit


class ThriftLintError(Exception):
  """Raised on a lint failure."""


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
    register('--skip', action='store_true', help='Skip thrift linting.')
    register('--strict', default=None, action='store_true',
             help='Fail the goal if thrift linter errors are found.')
    cls.register_jvm_tool(register, 'scrooge-linter')

  @classmethod
  def product_types(cls):
    # Declare the product of this goal. Gen depends on thrift-linter.
    return ['thrift-linter']

  @classmethod
  def prepare(cls, options, round_manager):
    super(ThriftLinter, cls).prepare(options, round_manager)
    # Linter depends on ivy running before it.
    round_manager.require_data('ivy_imports')

  @property
  def config_section(self):
    return self._CONFIG_SECTION

  @staticmethod
  def _to_bool(value):
    # Converts boolean and string values to boolean.
    return str(value) == 'True'

  def _is_strict(self, target):
    # TODO: the new options parsing doesn't support this. This task wants the target in the BUILD
    # file to be able to override a value in the pants.ini file. Finally, command-line overrides
    # that. But parsing of options combines the command-line values and pants.ini values in a single
    # "merged" view, into which there's no opportunity to inject an override from the BUILD target.

    # The strict value is read from the following, in order:
    # 1. command line, --[no-]strict
    # 2. java_thrift_library target in BUILD file, thrift_linter_strict = False,
    # 3. pants.ini, [thrift-linter] section, strict field.
    # 4. default = False
    cmdline_strict = self.get_options().strict

    if cmdline_strict is not None:
      return self._to_bool(cmdline_strict)

    if target.thrift_linter_strict is not None:
      return self._to_bool(target.thrift_linter_strict)

    return self._to_bool(self.context.config.get(self._CONFIG_SECTION, 'strict',
                                                 default=ThriftLinter.STRICT_DEFAULT))

  def _lint(self, target):
    self.context.log.debug('Linting {0}'.format(target.address.spec))

    classpath = self.tool_classpath('scrooge-linter')

    config_args = self.context.config.getlist(self._CONFIG_SECTION, 'linter_args', default=[])
    if not self._is_strict(target):
      config_args.append('--ignore-errors')

    paths = target.sources_relative_to_buildroot()

    args = config_args + paths

    # If runjava returns non-zero, this marks the workunit as a
    # FAILURE, and there is no way to wrap this here.
    returncode = self.runjava(classpath=classpath,
                              main='com.twitter.scrooge.linter.Main',
                              args=args,
                              workunit_labels=[WorkUnit.COMPILER])  # to let stdout/err through.

    if returncode != 0:
      raise ThriftLintError(
        'Lint errors in target {0} for {1}.'.format(target.address.spec, paths))

  def execute(self):
    if self.get_options().skip:
      return

    thrift_targets = self.context.targets(self._is_thrift)
    with self.invalidated(thrift_targets) as invalidation_check:
      errors = []
      for vt in invalidation_check.invalid_vts:
        try:
          self._lint(vt.target)
        except ThriftLintError as e:
          errors.append(str(e))
        else:
          vt.update()
      if errors:
        raise TaskError('\n'.join(errors))
