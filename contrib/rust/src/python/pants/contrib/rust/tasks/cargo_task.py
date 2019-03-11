# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os
import pprint

from pants.base.build_environment import get_buildroot
from pants.base.workunit import WorkUnit
from pants.task.task import Task
from pants.util.process_handler import subprocess

from pants.contrib.rust.targets.original.cargo_base import CargoBase
from pants.contrib.rust.targets.original.cargo_binary import CargoBinary
from pants.contrib.rust.targets.original.cargo_library import CargoLibrary
from pants.contrib.rust.targets.original.cargo_workspace import CargoWorkspace
from pants.contrib.rust.targets.synthetic.cargo_project_binary import CargoProjectBinary
from pants.contrib.rust.targets.synthetic.cargo_project_library import CargoProjectLibrary
from pants.contrib.rust.targets.synthetic.cargo_project_test import CargoProjectTest
from pants.contrib.rust.targets.synthetic.cargo_synthetic_base import CargoSyntheticBase
from pants.contrib.rust.targets.synthetic.cargo_synthetic_binary import CargoSyntheticBinary
from pants.contrib.rust.targets.synthetic.cargo_synthetic_custom_build import \
  CargoSyntheticCustomBuild
from pants.contrib.rust.targets.synthetic.cargo_synthetic_library import CargoSyntheticLibrary
from pants.contrib.rust.targets.synthetic.cargo_synthetic_proc_macro import CargoSyntheticProcMacro


class CargoTask(Task):

  pp = pprint.PrettyPrinter(indent=2)

  @staticmethod
  def manifest_name():
    return 'Cargo.toml'

  @staticmethod
  def is_cargo_original(target):
    return isinstance(target, CargoBase)

  @staticmethod
  def is_cargo_original_binary(target):
    return isinstance(target, CargoBinary)

  @staticmethod
  def is_cargo_original_library(target):
    return isinstance(target, CargoLibrary)

  @staticmethod
  def is_cargo_original_workspace(target):
    return isinstance(target, CargoWorkspace)

  @staticmethod
  def is_cargo_synthetic(target):
    return isinstance(target, CargoSyntheticBase)

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
  def is_cargo_project_binary(target):
    return isinstance(target, CargoProjectBinary)

  @staticmethod
  def is_cargo_project_library(target):
    return isinstance(target, CargoProjectLibrary)

  @staticmethod
  def is_cargo_project_test(target):
    return isinstance(target, CargoProjectTest)

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
        current_env[name] = "{}:{}".format(current_env[name], env_value).encode('utf-8')
      else:
        current_env[name] = env_value.encode('utf-8')
    return current_env

  def execute_command(self, command, workunit_name, workunit_labels, current_working_dir=None,
                      env_vars=None):

    current_working_dir = current_working_dir or get_buildroot()
    env_vars = env_vars or {}

    with self.context.new_workunit(name=workunit_name,
                                   labels=workunit_labels,
                                   cmd=str(command)) as workunit:

      proc_env = self._set_env_vars(env_vars)

      self.context.log.debug(
        'Run\n\tCMD: {0}\n\tENV: {1}\n\tCWD: {2}'.format(self.pretty(command),
                                                         self.pretty(proc_env),
                                                         current_working_dir))

      try:
        subprocess.check_call(command,
                              env=proc_env,
                              cwd=current_working_dir,
                              stdout=workunit.output('stdout'),
                              stderr=workunit.output('stderr'))
      except subprocess.CalledProcessError:
        workunit.set_outcome(WorkUnit.FAILURE)
      workunit.set_outcome(WorkUnit.SUCCESS)

    return workunit.outcome()

  def execute_command_and_get_output(self, command, workunit_name, workunit_labels, env_vars=None,
                                     current_working_dir=None):

    current_working_dir = current_working_dir or get_buildroot()
    env_vars = env_vars or {}

    with self.context.new_workunit(name=workunit_name,
                                   labels=workunit_labels,
                                   cmd=str(command)) as workunit:
      proc_env = self._set_env_vars(env_vars)

      self.context.log.debug(
        'Run\n\tCMD: {0}\n\tENV: {1}\n\tCWD: {2}'.format(self.pretty(command),
                                                         self.pretty(proc_env),
                                                         current_working_dir))

      proc = subprocess.Popen(command,
                              env=proc_env,
                              cwd=current_working_dir,
                              stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE)

      std_out, std_err = proc.communicate()

      returncode = proc.returncode
      workunit.set_outcome(WorkUnit.SUCCESS if returncode == 0 else WorkUnit.FAILURE)

    return workunit.outcome(), std_out.decode('utf-8'), std_err.decode('utf-8')

  def pretty(self, obj):
    return self.pp.pformat(obj)
