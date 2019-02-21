# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os

from pants.task.task import Task
from pants.util.process_handler import subprocess

from pants.contrib.rust.targets.cargo_base_binary import CargoBaseBinary
from pants.contrib.rust.targets.cargo_base_custom_build import CargoBaseCustomBuild
from pants.contrib.rust.targets.cargo_base_library import CargoBaseLibrary
from pants.contrib.rust.targets.cargo_base_proc_macro import CargoBaseProcMacro
from pants.contrib.rust.targets.cargo_base_target import CargoBaseTarget
from pants.contrib.rust.targets.cargo_binary import CargoBinary
from pants.contrib.rust.targets.cargo_library import CargoLibrary
from pants.contrib.rust.targets.cargo_synthetic_binary import CargoSyntheticBinary
from pants.contrib.rust.targets.cargo_synthetic_custom_build import CargoSyntheticCustomBuild
from pants.contrib.rust.targets.cargo_synthetic_library import CargoSyntheticLibrary
from pants.contrib.rust.targets.cargo_synthetic_proc_macro import CargoSyntheticProcMacro
from pants.contrib.rust.targets.cargo_target import CargoTarget
from pants.contrib.rust.targets.cargo_test import CargoTest
from pants.contrib.rust.targets.cargo_workspace import CargoWorkspace


class CargoTask(Task):

  @staticmethod
  def manifest_name():
    return 'Cargo.toml'

  @staticmethod
  def is_cargo_binary(target):
    return isinstance(target, CargoBinary)

  @staticmethod
  def is_workspace(target):
    return isinstance(target, CargoWorkspace)

  @staticmethod
  def is_cargo_workspace(target):
    return isinstance(target, CargoWorkspace)

  @staticmethod
  def is_cargo_base_target(target):
    return isinstance(target, CargoBaseTarget)

  @staticmethod
  def is_cargo_base_library(target):
    return isinstance(target, CargoBaseLibrary)

  @staticmethod
  def is_cargo_base_binary(target):
    return isinstance(target, CargoBaseBinary)

  @staticmethod
  def is_cargo_base_custom_build(target):
    return isinstance(target, CargoBaseCustomBuild)

  @staticmethod
  def is_cargo_base_proc_macro(target):
    return isinstance(target, CargoBaseProcMacro)

  @staticmethod
  def is_cargo_synthetic_library(target):
    return isinstance(target, CargoSyntheticLibrary)

  @staticmethod
  def is_cargo_synthetic_binary(target):
    return isinstance(target, CargoSyntheticBinary)

  @staticmethod
  def is_cargo_synthetic_custom_build(target):
    return isinstance(target, CargoSyntheticCustomBuild)

  @staticmethod
  def is_cargo_synthetic_proc_macro(target):
    return isinstance(target, CargoSyntheticProcMacro)

  @staticmethod
  def is_cargo(target):
    return isinstance(target, CargoTarget)

  @staticmethod
  def is_cargo_library(target):
    return isinstance(target, CargoLibrary)

  @staticmethod
  def is_cargo_test(target):
    return isinstance(target, CargoTest)

  def _add_env_var(self, dict, name, value, extend=False):
    dict.update({name: (value, extend)})
    return dict

  def _add_env_vars(self, dict, other_dict, extend=False):
    for name, value in other_dict.items():
      self._add_env_var(dict, name, value, extend)
    return dict

  def _set_env_vars(self, env_vars):
    current_env = os.environ.copy()
    for name, value in env_vars.items():
      env_value, extend = value
      if extend:
        current_env[name] = "{}:{}".format(current_env[name], env_value.encode('utf-8'))
      else:
        current_env[name] = env_value.encode('utf-8')
    return current_env

  def run_command(self, command, current_working_dir, env_vars, workunit):
    std_out = workunit.output('stdout')
    std_err = workunit.output('stderr')

    proc_env = self._set_env_vars(env_vars)

    self.context.log.debug(
      'Run\n\tCMD: {0}\n\tENV: {1}\n\tCWD: {2}'.format(command, proc_env, current_working_dir))

    try:
      subprocess.check_call(command, stdout=std_out, stderr=std_err, cwd=current_working_dir,
                            env=proc_env)
    except subprocess.CalledProcessError:
      workunit.set_outcome(1)
    workunit.set_outcome(3)

  def run_command_and_get_output(self, command, current_working_dir, env_vars, workunit):
    proc_env = self._set_env_vars(env_vars)

    self.context.log.debug(
      'Run\n\tCMD: {0}\n\tENV: {1}\n\tCWD: {2}'.format(command, proc_env, current_working_dir))

    proc = subprocess.Popen(command, stdout=subprocess.PIPE, env=proc_env, cwd=current_working_dir)

    std_output = proc.communicate()
    workunit.set_outcome(3)
    return std_output[0].decode('utf-8')
