# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from builtins import str

from pants.engine.legacy.graph import HydratedTarget
from pants.engine.rules import rule
from pants.engine.selectors import Select
from pants.rules.core.core_test_model import Status, TestResult


# This class currently exists so that other rules could be added which turned a HydratedTarget into
# a language-specific test result, and could be installed alongside run_python_test.
# Hopefully https://github.com/pantsbuild/pants/issues/4535 should help resolve this.
class PyTestResult(TestResult):
  pass


@rule(PyTestResult, [Select(HydratedTarget)])
def run_python_test(target):
  # TODO: Actually run tests (https://github.com/pantsbuild/pants/issues/6003)

  if 'fail' in target.address.reference():
    noun = 'failed'
    status = Status.FAILURE
  else:
    noun = 'passed'
    status = Status.SUCCESS
  return PyTestResult(status=status, stdout=str('I am a python test which {}'.format(noun)))
