# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import subprocess

from pants.fs.archive import ZIP
from pants.util.contextutil import temporary_dir
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class JvmRunIntegrationTest(PantsRunIntegrationTest):

  def _exec_run(self, target, *args):
    ''' invokes pants goal run <target>
    :param target: target name to compile
    :param args: list of arguments to append to the command
    :return: stdout as a string on success, raises an Exception on error
    '''
    # Avoid some known-to-choke-on interpreters.
    command = ['goal', 'run', target,
               '--interpreter=CPython>=2.6,<3',
               '--interpreter=CPython>=3.3'] + list(args)
    pants_run = self.run_pants(command)
    self.assertEquals(pants_run.returncode, self.PANTS_SUCCESS_CODE,
                      "goal run expected success, got {0}\n"
                      "got stderr:\n{1}\n"
                      "got stdout:\n{2}\n".format(pants_run.returncode,
                                                  pants_run.stderr_data,
                                                  pants_run.stdout_data))

    return pants_run.stdout_data

  def test_run_colliding_resources(self):
    """
    Tests that the proper resource is bundled with each of these bundled targets when
    each project has a different resource with the same path.
    """
    for name in ['a', 'b', 'c']:
      target = ('testprojects/maven_layout/resource_collision/example_{name}'
                '/src/main/java/com/pants/duplicateres/example{name}/'
                .format(name=name))
      stdout = self._exec_run(target)
      expected = 'Hello world!: resource from example {name}\n'.format(name=name)
      self.assertIn(expected, stdout)

  def test_run_cwd(self):
    """Tests the --cwd option that allows the working directory to change when running."""

    # Make sure the test fails if you don't specify a directory
    pants_run = self.run_pants(['goal', 'run',
                               'testprojects/src/java/com/pants/testproject/cwdexample',
                               '--interpreter=CPython>=2.6,<3',
                               '--interpreter=CPython>=3.3'])
    self.assert_failure(pants_run)
    self.assertIn('Neither ExampleCwd.java nor readme.txt found.', pants_run.stdout_data)

    # Implicit cwd based on target
    stdout_data = self._exec_run('testprojects/src/java/com/pants/testproject/cwdexample',
                                 '--run-jvm-cwd')
    self.assertIn('Found ExampleCwd.java', stdout_data)

    # Explicit cwd specified
    stdout_data = self._exec_run('testprojects/src/java/com/pants/testproject/cwdexample',
                                 '--run-jvm-cwd=testprojects/src/java/com/pants/testproject/cwdexample/subdir')
    self.assertIn('Found readme.txt', stdout_data)

