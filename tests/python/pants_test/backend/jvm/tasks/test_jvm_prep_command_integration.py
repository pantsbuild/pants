# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.util.contextutil import open_zip, temporary_dir
from pants.util.dirutil import safe_delete
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class JvmPrepCommandIntegration(PantsRunIntegrationTest):

  def setUp(self):
    safe_delete('/tmp/running-in-goal-test')
    safe_delete('/tmp/running-in-goal-binary')
    safe_delete('/tmp/running-in-goal-compile.jar')

  def assert_prep_compile(self):
    with temporary_dir() as tempdir:
      with open_zip('/tmp/running-in-goal-compile.jar') as jar:
        self.assertEquals(sorted(['BUILD',
                                  'ExampleJvmPrepCommand.java',
                                  'META-INF/', 'META-INF/MANIFEST.MF']),
                          sorted(jar.namelist()))

  def test_jvm_prep_command_in_compile(self):
    pants_run = self.run_pants([
      'compile',
      'testprojects/src/java/org/pantsbuild/testproject/jvmprepcommand::'])
    self.assert_success(pants_run)

    self.assertTrue(os.path.exists('/tmp/running-in-goal-compile.jar'))
    self.assertFalse(os.path.exists('/tmp/running-in-goal-test'))
    self.assertFalse(os.path.exists('/tmp/running-in-goal-binary'))

    self.assert_prep_compile()

  def test_jvm_prep_command_in_test(self):
    pants_run = self.run_pants([
      'test',
      'testprojects/src/java/org/pantsbuild/testproject/jvmprepcommand::'])
    self.assert_success(pants_run)

    self.assertTrue(os.path.exists('/tmp/running-in-goal-compile.jar'))
    self.assertFalse(os.path.exists('/tmp/running-in-goal-binary'))

    with open('/tmp/running-in-goal-test') as f:
      prep_output = f.read()

    expected = """Running: org.pantsbuild.testproject.jvmprepcommand.ExampleJvmPrepCommand
args are: "/tmp/running-in-goal-test","foo",
org.pantsbuild properties: "org.pantsbuild.jvm_prep_command=WORKS-IN-TEST"
"""
    self.assertEquals(expected, prep_output)
    self.assert_prep_compile()

  def test_jvm_prep_command_in_binary(self):
    pants_run = self.run_pants([
      'binary',
      'testprojects/src/java/org/pantsbuild/testproject/jvmprepcommand::'])
    self.assert_success(pants_run)

    self.assertTrue(os.path.exists('/tmp/running-in-goal-compile.jar'))
    self.assertFalse(os.path.exists('/tmp/running-in-goal-test'))

    with open('/tmp/running-in-goal-binary') as f:
      prep_output = f.read()

    expected = """Running: org.pantsbuild.testproject.jvmprepcommand.ExampleJvmPrepCommand
args are: "/tmp/running-in-goal-binary","bar",
org.pantsbuild properties: "org.pantsbuild.jvm_prep_command=WORKS-IN-BINARY"
"""
    self.assertEquals(expected, prep_output)
    self.assert_prep_compile()
