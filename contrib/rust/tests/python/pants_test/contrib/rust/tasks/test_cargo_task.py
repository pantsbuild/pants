# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os
import string
from textwrap import dedent

from pants.base.workunit import WorkUnitLabel
from pants.build_graph.target import Target
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import chmod_plus_x
from pants_test.task_test_base import TaskTestBase

from pants.contrib.rust.targets.original.cargo_base import CargoBase
from pants.contrib.rust.targets.original.cargo_binary import CargoBinary
from pants.contrib.rust.targets.original.cargo_library import CargoLibrary
from pants.contrib.rust.targets.synthetic.cargo_project_binary import CargoProjectBinary
from pants.contrib.rust.targets.synthetic.cargo_project_library import CargoProjectLibrary
from pants.contrib.rust.targets.synthetic.cargo_project_test import CargoProjectTest
from pants.contrib.rust.targets.synthetic.cargo_synthetic_base import CargoSyntheticBase
from pants.contrib.rust.targets.synthetic.cargo_synthetic_binary import CargoSyntheticBinary
from pants.contrib.rust.targets.synthetic.cargo_synthetic_custom_build import \
  CargoSyntheticCustomBuild
from pants.contrib.rust.targets.synthetic.cargo_synthetic_library import CargoSyntheticLibrary
from pants.contrib.rust.tasks.cargo_task import CargoTask


test_shell_script = dedent("""       
        #!/bin/bash
        
        if [ "$EXECUTE_COMMAND_TEST" = "{execute_command_test_var}" ]; then
          echo success
          exit 0
        else
          >&2 echo error
          exit 1
        fi
        """)


class CargoTaskTest(TaskTestBase):

  class TestCargoTask(CargoTask):

    def execute(self):
      raise NotImplementedError()

  @classmethod
  def task_type(cls):
    return cls.TestCargoTask

  def test_is_cargo_original(self):
    expected = {
        CargoBase: True,
        CargoBinary: True,
        CargoLibrary: True,
        # CargoWorkspace: True,
        CargoProjectBinary: False,
        CargoProjectLibrary: False,
        CargoProjectTest: False,
        CargoSyntheticBase: False,
        CargoSyntheticBinary: False,
        CargoSyntheticCustomBuild: False,
        CargoSyntheticLibrary: False,
        Target: False,
    }
    self.assertEqual(expected, self._type_check(expected.keys(), CargoTask.is_cargo_original))

  def test_is_cargo_original_binary(self):
    expected = {
        CargoBase: False,
        CargoBinary: True,
        CargoLibrary: False,
        # CargoWorkspace: False,
        CargoProjectBinary: False,
        CargoProjectLibrary: False,
        CargoProjectTest: False,
        CargoSyntheticBase: False,
        CargoSyntheticBinary: False,
        CargoSyntheticCustomBuild: False,
        CargoSyntheticLibrary: False,
        Target: False,
    }
    self.assertEqual(expected, self._type_check(expected.keys(),
                                                CargoTask.is_cargo_original_binary))

  def test_is_cargo_original_library(self):
    expected = {
        CargoBase: False,
        CargoBinary: False,
        CargoLibrary: True,
        # CargoWorkspace: False,
        CargoProjectBinary: False,
        CargoProjectLibrary: False,
        CargoProjectTest: False,
        CargoSyntheticBase: False,
        CargoSyntheticBinary: False,
        CargoSyntheticCustomBuild: False,
        CargoSyntheticLibrary: False,
        Target: False,
    }
    self.assertEqual(expected, self._type_check(expected.keys(),
                                                CargoTask.is_cargo_original_library))

  def test_is_cargo_original_workspace(self):
    expected = {
        CargoBase: False,
        CargoBinary: False,
        CargoLibrary: False,
        # CargoWorkspace: True,
        CargoProjectBinary: False,
        CargoProjectLibrary: False,
        CargoProjectTest: False,
        CargoSyntheticBase: False,
        CargoSyntheticBinary: False,
        CargoSyntheticCustomBuild: False,
        CargoSyntheticLibrary: False,
        Target: False,
    }
    self.assertEqual(expected,
                     self._type_check(expected.keys(), CargoTask.is_cargo_original_workspace))

  def test_is_cargo_synthetic(self):
    expected = {
        CargoBase: False,
        CargoBinary: False,
        CargoLibrary: False,
        # CargoWorkspace: False,
        CargoProjectBinary: True,
        CargoProjectLibrary: True,
        CargoProjectTest: True,
        CargoSyntheticBase: True,
        CargoSyntheticBinary: True,
        CargoSyntheticCustomBuild: True,
        CargoSyntheticLibrary: True,
        Target: False,
    }
    self.assertEqual(expected, self._type_check(expected.keys(), CargoTask.is_cargo_synthetic))

  def test_is_cargo_synthetic_library(self):
    expected = {
        CargoBase: False,
        CargoBinary: False,
        CargoLibrary: False,
        # CargoWorkspace: False,
        CargoProjectBinary: False,
        CargoProjectLibrary: True,
        CargoProjectTest: False,
        CargoSyntheticBase: False,
        CargoSyntheticBinary: False,
        CargoSyntheticCustomBuild: False,
        CargoSyntheticLibrary: True,
        Target: False,
    }
    self.assertEqual(expected,
                     self._type_check(expected.keys(), CargoTask.is_cargo_synthetic_library))

  def test_is_cargo_synthetic_binary(self):
    expected = {
        CargoBase: False,
        CargoBinary: False,
        CargoLibrary: False,
        # CargoWorkspace: False,
        CargoProjectBinary: True,
        CargoProjectLibrary: False,
        CargoProjectTest: False,
        CargoSyntheticBase: False,
        CargoSyntheticBinary: True,
        CargoSyntheticCustomBuild: False,
        CargoSyntheticLibrary: False,
        Target: False,
    }
    self.assertEqual(expected, self._type_check(expected.keys(),
                                                CargoTask.is_cargo_synthetic_binary))

  def test_is_cargo_synthetic_custom_build(self):
    expected = {
        CargoBase: False,
        CargoBinary: False,
        CargoLibrary: False,
        # CargoWorkspace: False,
        CargoProjectBinary: False,
        CargoProjectLibrary: False,
        CargoProjectTest: False,
        CargoSyntheticBase: False,
        CargoSyntheticBinary: False,
        CargoSyntheticCustomBuild: True,
        CargoSyntheticLibrary: False,
        Target: False,
    }
    self.assertEqual(expected,
                     self._type_check(expected.keys(), CargoTask.is_cargo_synthetic_custom_build))

  def test_is_cargo_project_binary(self):
    expected = {
        CargoBase: False,
        CargoBinary: False,
        CargoLibrary: False,
        # CargoWorkspace: False,
        CargoProjectBinary: True,
        CargoProjectLibrary: False,
        CargoProjectTest: False,
        CargoSyntheticBase: False,
        CargoSyntheticBinary: False,
        CargoSyntheticCustomBuild: False,
        CargoSyntheticLibrary: False,
        Target: False,
    }
    self.assertEqual(expected, self._type_check(expected.keys(), CargoTask.is_cargo_project_binary))

  def test_is_cargo_project_library(self):
    expected = {
        CargoBase: False,
        CargoBinary: False,
        CargoLibrary: False,
        # CargoWorkspace: False,
        CargoProjectBinary: False,
        CargoProjectLibrary: True,
        CargoProjectTest: False,
        CargoSyntheticBase: False,
        CargoSyntheticBinary: False,
        CargoSyntheticCustomBuild: False,
        CargoSyntheticLibrary: False,
        Target: False,
    }
    self.assertEqual(expected, self._type_check(expected.keys(),
                                                CargoTask.is_cargo_project_library))

  def test_is_cargo_project_test(self):
    expected = {
        CargoBase: False,
        CargoBinary: False,
        CargoLibrary: False,
        # CargoWorkspace: False,
        CargoProjectBinary: False,
        CargoProjectLibrary: False,
        CargoProjectTest: True,
        CargoSyntheticBase: False,
        CargoSyntheticBinary: False,
        CargoSyntheticCustomBuild: False,
        CargoSyntheticLibrary: False,
        Target: False,
    }
    self.assertEqual(expected, self._type_check(expected.keys(), CargoTask.is_cargo_project_test))

  def _type_check(self, types, type_check_function):
    # Make sure the diff display length is long enough for the test_is_* tests.
    # It's a little weird to include this side effect here, but otherwise it would have to
    # be duplicated or go in the setup (in which case it would affect all tests).
    self.maxDiff = None

    target_names = [':' + letter for letter in list(string.ascii_lowercase)]
    types_with_target_names = zip(types, target_names)

    type_check_results = {
        type: type_check_function(self.make_target(target_name, type))
        for type, target_name in types_with_target_names
    }

    return type_check_results

  def test_execute_command_success(self):
    task = self.create_task(self.context())
    with temporary_dir() as chroot:
      script = os.path.join(chroot, 'test.sh')
      execute_command_test_var = 'Test'
      with open(script, 'w') as fp:
        fp.write(
            test_shell_script.format(execute_command_test_var=execute_command_test_var).strip())

      chmod_plus_x(script)
      returncode = task.execute_command(
          [script],
          'test', [WorkUnitLabel.TEST],
          env_vars={'EXECUTE_COMMAND_TEST': (execute_command_test_var, False)},
          current_working_dir=chroot)

      self.assertEqual(0, returncode)

  def test_execute_command_failure(self):
    task = self.create_task(self.context())
    with temporary_dir() as chroot:
      script = os.path.join(chroot, 'test.sh')
      execute_command_test_var = 'Test'
      with open(script, 'w') as fp:
        fp.write(
            test_shell_script.format(execute_command_test_var=execute_command_test_var).strip())

      chmod_plus_x(script)
      returncode = task.execute_command([script],
                                        'test', [WorkUnitLabel.TEST],
                                        current_working_dir=chroot)

      self.assertEqual(1, returncode)

  def test_execute_command_and_get_output_success(self):
    task = self.create_task(self.context())
    with temporary_dir() as chroot:
      script = os.path.join(chroot, 'test.sh')
      execute_command_test_var = 'Test'
      with open(script, 'w') as fp:
        fp.write(
            test_shell_script.format(execute_command_test_var=execute_command_test_var).strip())

      chmod_plus_x(script)
      returncode, std_out, std_err = task.execute_command_and_get_output(
          [script],
          'test', [WorkUnitLabel.TEST],
          env_vars={'EXECUTE_COMMAND_TEST': (execute_command_test_var, False)},
          current_working_dir=chroot)

      self.assertEqual(0, returncode)
      self.assertEqual("success\n", std_out)
      self.assertEqual("", std_err)

  def test_execute_command_and_get_output_failure(self):
    task = self.create_task(self.context())
    with temporary_dir() as chroot:
      script = os.path.join(chroot, 'test.sh')
      execute_command_test_var = 'Test'
      with open(script, 'w') as fp:
        fp.write(
            test_shell_script.format(execute_command_test_var=execute_command_test_var).strip())

      chmod_plus_x(script)
      returncode, std_out, std_err = task.execute_command_and_get_output([script],
                                                                         'test',
                                                                         [WorkUnitLabel.TEST],
                                                                         current_working_dir=chroot)

      self.assertEqual(1, returncode)
      self.assertEqual("", std_out)
      self.assertEqual("error\n", std_err)
