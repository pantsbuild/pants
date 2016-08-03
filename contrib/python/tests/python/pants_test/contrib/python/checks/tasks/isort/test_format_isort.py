# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


TEST_DIR = 'testprojects/src/python/isort/python'


class IntegrationTests(PantsRunIntegrationTest):
  def test_isort(self):
    target = '{}:bad-order'.format(TEST_DIR)

    # initial test should fail because of style error.
    initial_test = self.run_pants(
      ['compile.pythonstyle',
       '--compile-python-eval-skip',
       target
       ]
    )
    self.assert_failure(initial_test)

    # call format.isort to format the files.
    format_run = self.run_pants(['format.isort', '--config-file=.isort.cfg', target])
    self.assert_success(format_run)

    # final test should pass because files have been formatted.
    final_test = self.run_pants(
      ['compile.pythonstyle',
       '--compile-python-eval-skip',
       target
       ]
    )
    self.assert_success(final_test)

  def tearDown(self):
    # tests change code, so they need to be reset.
    subprocess.check_call(['git', 'co', '--', TEST_DIR])
