# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.base.exceptions import TaskError
from pants.task.console_task import ConsoleTask

from pants.contrib.buildrefactor.buildozer import Buildozer


class PrintTarget(ConsoleTask):
  """Print's a specified target if found in the associated build file

    line-number: optional flag to print the starting and ending line numbers of the target

    Example:
      $./pants print-target --line-number testprojects/tests/java/org/pantsbuild/testproject/dummies:passing_target
  """

  @classmethod
  def register_options(cls, register):
    super(PrintTarget, cls).register_options(register)

    register('--line-number', help='Prints the starting line number of the named target.', type=bool, default=False)

  def __init__(self, *args, **kwargs):
    super(PrintTarget, self).__init__(*args, **kwargs)

    if len(self.context.target_roots) > 1:
      raise TaskError('More than one target specified:\n{}'.format(str(self.context.target_roots)))

    self.target = self.context.target_roots[0]
    self.options = self.get_options()

  def console_output(self, targets):

    spec_path = self.target.address.spec

    yield('\'{}\' found in BUILD file.\n'.format(self.target.name))

    if self.options.line_number:
      startline_output = Buildozer.return_buildozer_output(spec = spec_path, command = 'print startline', suppress_warnings=True)
      startline_digit = int(filter(str.isdigit, startline_output))

      endline_output = Buildozer.return_buildozer_output(spec = spec_path, command = 'print endline', suppress_warnings=True)
      endline_digit = int(filter(str.isdigit, endline_output))

      yield('Line numbers: {}-{}.\n'.format(startline_digit, endline_digit))

    yield('Target definiton:\n\n{}'.format(Buildozer.return_buildozer_output(spec = spec_path, command = 'print rule', suppress_warnings=True)))
