# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import subprocess
from textwrap import dedent

from pants.util.contextutil import temporary_dir
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class PythonIsortIntegrationTest(PantsRunIntegrationTest):
  TEST_DIR = 'testprojects/src/python/isort/python'

  CONFIG = dedent("""
    [settings]
    line_length=100
    known_future_library=future,pies
    known_first_party=twitter,com.twitter
    known_gen=gen
    indent=2
    multi_line_output=0
    default_section=THIRDPARTY
    sections=FUTURE,STDLIB,FIRSTPARTY,THIRDPARTY
  """)

  def test_isort(self):
    target = '{}:bad-order'.format(self.TEST_DIR)

    # initial test should fail because of style error.
    args = [
      'compile.pythonstyle',
      '--compile-python-eval-skip',
      '--no-pycheck-import-order-skip',
      target
    ]

    initial_test = self.run_pants(args)
    self.assert_failure(initial_test)

    # call fmt.isort to format the files.
    with temporary_dir() as dir:
      with open(os.path.join(dir, '.isort.cfg'), 'w') as cfg:
        cfg.write(self.CONFIG)
        cfg.close()

      format_run = self.run_pants(['fmt.isort', '--settings-path={}'.format(cfg.name), target])
      self.assert_success(format_run)

    # final test should pass because files have been formatted.
    final_test = self.run_pants(args)
    self.assert_success(final_test)

  def tearDown(self):
    # tests change code, so they need to be reset.
    subprocess.check_call(['git', 'checkout', '--', self.TEST_DIR])
