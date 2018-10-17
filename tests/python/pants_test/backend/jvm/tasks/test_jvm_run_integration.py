# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class JvmRunIntegrationTest(PantsRunIntegrationTest):

  def _exec_run(self, target, *args):
    ''' invokes pants goal run <target>
    :param target: target name to compile
    :param args: list of arguments to append to the command
    :return: stdout as a string on success, raises an Exception on error
    '''
    # Avoid some known-to-choke-on interpreters.
    command = ['run',
               target,
               '--python-setup-interpreter-constraints=CPython>=2.7,<3',
               '--python-setup-interpreter-constraints=CPython>=3.3'] + list(args)
    pants_run = self.run_pants(command)
    self.assert_success(pants_run)
    return pants_run.stdout_data

  def test_run_colliding_resources(self):
    """
    Tests that the proper resource is bundled with each of these bundled targets when
    each project has a different resource with the same path.
    """
    for name in ['a', 'b', 'c']:
      target = ('testprojects/maven_layout/resource_collision/example_{name}'
                '/src/main/java/org/pantsbuild/duplicateres/example{name}/'
                .format(name=name))
      stdout = self._exec_run(target)
      expected = 'Hello world!: resource from example {name}\n'.format(name=name)
      self.assertIn(expected, stdout)

  def test_no_run_cwd(self):
    """Tests the --cwd option that allows the working directory to change when running."""

    # Make sure the test fails if you don't specify a directory
    pants_run = self.run_pants(['run',
                                'testprojects/src/java/org/pantsbuild/testproject/cwdexample',
                                '--python-setup-interpreter-constraints=CPython>=2.7,<3',
                                '--python-setup-interpreter-constraints=CPython>=3.3'])
    self.assert_failure(pants_run)
    self.assertIn('Neither ExampleCwd.java nor readme.txt found.', pants_run.stderr_data)

  def test_empty_run_cwd(self):
    # Implicit cwd based on target
    stdout_data = self._exec_run('testprojects/src/java/org/pantsbuild/testproject/cwdexample',
                                 '--run-jvm-cwd')
    self.assertIn('Found ExampleCwd.java', stdout_data)

  def test_explicit_run_cwd(self):
    # Explicit cwd specified
    stdout_data = self._exec_run('testprojects/src/java/org/pantsbuild/testproject/cwdexample',
                                 '--run-jvm-cwd='
                                 'testprojects/src/java/org/pantsbuild/testproject/cwdexample/subdir')
    self.assertIn('Found readme.txt', stdout_data)

  def test_disable_synthetic_jar(self):
    output = self.run_pants(
      ['run',
       'testprojects/tests/java/org/pantsbuild/testproject/syntheticjar:run']).stdout_data
    self.assertIn('Synthetic jar run is detected', output)

    output = self.run_pants(
      ['run',
       '--no-jvm-synthetic-classpath',
       'testprojects/tests/java/org/pantsbuild/testproject/syntheticjar:run']).stdout_data
    self.assertIn('Synthetic jar run is not detected', output)

  def test_enable_extra_jvm_options(self):
    output = self.run_pants(
      ['run',
        'testprojects/src/java/org/pantsbuild/testproject/extra_jvm_options:python_app']).stdout_data
    self.assertIn('Python app runs correctly', output)

    output = self.run_pants(
      ['run',
        'testprojects/src/java/org/pantsbuild/testproject/extra_jvm_options:noopts']).stdout_data
    self.assertIn("""Property property.color is null
Property property.size is null
Flag -DMyFlag is NOT set
Max Heap Size: 954728448""", output)

    output = self.run_pants(
      ['run',
        'testprojects/src/java/org/pantsbuild/testproject/extra_jvm_options:app_noopts']).stdout_data
    self.assertIn("""Property property.color is null
Property property.size is null
Flag -DMyFlag is NOT set
Max Heap Size: 954728448""", output)

    output = self.run_pants(
      ['run',
        'testprojects/src/java/org/pantsbuild/testproject/extra_jvm_options:opts']).stdout_data
    self.assertIn("""Property property.color is orange
Property property.size is 2
Flag -DMyFlag is set
Max Heap Size: 1572864""", output)
