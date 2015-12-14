# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from unittest import expectedFailure

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class ChangedTargetGoalsIntegrationTest(PantsRunIntegrationTest):
  def ref_for_greet_change(self):
    # Unfortunately, as in being an integration test, it is difficult to mock the SCM used.
    # Thus this will use the pants commit log, so we need a commit that changes greet example.
    # Any comment/whitespace/etc change is enough though, as long as we know the SHA.
    return '14cc5bc23561918dc7134427bfcb268506fcbcaa'

  def greet_classfile(self, workdir, filename):
    path = 'compile/jvm/java/classes/org/pantsbuild/example/hello/greet'.split('/')
    return os.path.join(workdir, *(path + [filename]))

  @expectedFailure
  def test_compile_changed(self):
    cmd = ['compile-changed', '--diffspec={}'.format(self.ref_for_greet_change())]

    with self.temporary_workdir() as workdir:
      # Nothing exists.
      self.assertFalse(os.path.exists(self.greet_classfile(workdir, 'Greeting.class')))
      self.assertFalse(os.path.exists(self.greet_classfile(workdir, 'GreetingTest.class')))

      run = self.run_pants_with_workdir(cmd, workdir)
      self.assert_success(run)

      # The directly changed target's produced classfile exists.
      self.assertTrue(os.path.exists(self.greet_classfile(workdir, 'Greeting.class')))
      self.assertFalse(os.path.exists(self.greet_classfile(workdir, 'GreetingTest.class')))

    with self.temporary_workdir() as workdir:
      # Nothing exists.
      self.assertFalse(os.path.exists(self.greet_classfile(workdir, 'Greeting.class')))
      self.assertFalse(os.path.exists(self.greet_classfile(workdir, 'GreetingTest.class')))

      run = self.run_pants_with_workdir(cmd + ['--include-dependees=direct'], workdir)
      self.assert_success(run)

      # The changed target's and its direct dependees' (eg its tests) classfiles exist.
      self.assertTrue(os.path.exists(self.greet_classfile(workdir, 'Greeting.class')))
      self.assertTrue(os.path.exists(self.greet_classfile(workdir, 'GreetingTest.class')))

  @expectedFailure
  def test_test_changed(self):
    with self.temporary_workdir() as workdir:
      cmd = ['test-changed', '--diffspec={}'.format(self.ref_for_greet_change())]
      junit_out = os.path.join(workdir, 'test', 'junit',
        'org.pantsbuild.example.hello.greet.GreetingTest.out.txt')

      self.assertFalse(os.path.exists(junit_out))

      run = self.run_pants_with_workdir(cmd, workdir)
      self.assert_success(run)

      self.assertFalse(os.path.exists(junit_out))

      run = self.run_pants_with_workdir(cmd + ['--include-dependees=direct'], workdir)
      self.assert_success(run)

      self.assertTrue(os.path.exists(junit_out))
