# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class IntransitiveIntegrationTest(PantsRunIntegrationTest):

  test_spec = 'testprojects/src/java/org/pantsbuild/testproject/intransitive'

  def assert_run_binary(self, main_class, expected_success, expected_data=(),
                        unexpected_data=()):
    result = self.run_pants([
      '--no-java-strict-deps',
      'run.jvm',
      '--main=org.pantsbuild.testproject.intransitive.{}'.format(main_class),
      self.test_spec,
    ])
    if not expected_success:
      self.assert_failure(result)
      return
    self.assert_success(result)
    for data in expected_data:
      self.assertIn(data, result.stdout_data)
    for data in unexpected_data:
      self.assertNotIn(data, result.stdout_data)

  def test_run_a_passes(self):
    self.assert_run_binary(
      main_class='A',
      expected_success=True,
      expected_data=['A is for Automata.', 'B is for Binary.'],
      unexpected_data=['C is for Code.'],
    )

  def test_run_b_passes(self):
    self.assert_run_binary(
      main_class='B',
      expected_success=True,
      expected_data=['B is for Binary.', 'I don\'t know what C is for.'],
      unexpected_data=['C is for Code.'],
    )

  def test_run_c_fails(self):
    self.assert_run_binary(
      main_class='C',
      expected_success=False,
    )
