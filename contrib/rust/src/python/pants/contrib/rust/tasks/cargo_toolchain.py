# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import distutils.spawn
import hashlib
import os

import requests
from future.utils import PY3
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnit, WorkUnitLabel
from pants.util.process_handler import subprocess

from pants.contrib.rust.tasks.cargo_task import CargoTask


class Toolchain(CargoTask):
  LAST_KNOWN_FINGERPRINT = '40328ad8fa5cfc15cdb0446bb812a4bba4c22b5aee195cfb8d64b8ef1de5879c'

  @classmethod
  def register_options(cls, register):
    super(Toolchain, cls).register_options(register)
    register(
      '--toolchain',
      type=str,
      default=None,
      help='Toolchain')

  @classmethod
  def product_types(cls):
    return ['cargo_env']

  @classmethod
  def implementation_version(cls):
    return super(Toolchain, cls).implementation_version() + [('Cargo_Toolchain', 1)]

  def setup_rustup(self):
    self.context.log.info('Installing rustup...')
    install_script = self.download_rustup_install_script()
    self.check_integrity_of_rustup_install_script(install_script.text)

    with self.context.new_workunit(name='setup-rustup',
                                   labels=[WorkUnitLabel.BOOTSTRAP]) as workunit:
      cmd = 'curl https://sh.rustup.rs -sSf | sh -s -- -y'  # -y Disable confirmation prompt.
      self.run_shell_command(cmd, workunit)

      if workunit.outcome() != WorkUnit.SUCCESS:
        self.context.log.error(workunit.outcome_string(workunit.outcome()))
      else:
        self.context.log.info(workunit.outcome_string(workunit.outcome()))

  def run_shell_command(self, command, workunit):
    std_out = workunit.output('stdout')
    std_err = workunit.output('stderr')

    try:
      subprocess.check_call(command, shell=True, stdout=std_out, stderr=std_err)
    except subprocess.CalledProcessError as e:
      workunit.set_outcome(1)
      std_err.write('Execution failed: {0}'.format(e))
    workunit.set_outcome(3)

  def download_rustup_install_script(self):
    return requests.get('https://sh.rustup.rs')

  def check_integrity_of_rustup_install_script(self, install_script):
    hasher = hashlib.sha256(install_script.encode('utf-8'))
    current_fingerprint = hasher.hexdigest() if PY3 else hasher.hexdigest().decode('utf-8')
    if current_fingerprint != self.LAST_KNOWN_FINGERPRINT:
      raise TaskError(
        'The fingerprint of the rustup script has changed!\nLast known: {0}\ncurrent: {1}'.format(
          self.LAST_KNOWN_FINGERPRINT, current_fingerprint))

  def install_rust_toolchain(self, toolchain):
    self.context.log.info('Installing toolchain: {0}'.format(toolchain))
    with self.context.new_workunit(name='install-rustup-toolchain',
                                   labels=[WorkUnitLabel.BOOTSTRAP]) as workunit:
      cmd = ['rustup', 'install', toolchain]

      env = {
        'PATH': (self.context.products.get_data('cargo_env')['PATH'], True)
      }

      self.run_command(cmd, get_buildroot(), env, workunit)

      if workunit.outcome() != WorkUnit.SUCCESS:
        self.context.log.error(workunit.outcome_string(workunit.outcome()))
      else:
        self.context.log.info(workunit.outcome_string(workunit.outcome()))

  def set_new_toolchain_as_default(self, toolchain):
    self.context.log.info('Set {0} as default toolchain'.format(toolchain))
    with self.context.new_workunit(name='setup-rustup-toolchain',
                                   labels=[WorkUnitLabel.BOOTSTRAP]) as workunit:
      cmd = ['rustup', 'default', toolchain]

      env = {
        'PATH': (self.context.products.get_data('cargo_env')['PATH'], True)
      }

      self.run_command(cmd, get_buildroot(), env, workunit)

      if workunit.outcome() != WorkUnit.SUCCESS:
        self.context.log.error(workunit.outcome_string(workunit.outcome()))
      else:
        self.context.log.info(workunit.outcome_string(workunit.outcome()))

  @staticmethod
  def check_if_rustup_exist():
    return distutils.spawn.find_executable('rustup') is not None

  def setup_toolchain(self):
    toolchain = self.get_options().toolchain
    if toolchain:
      self.install_rust_toolchain(toolchain)
      self.set_new_toolchain_as_default(toolchain)

  def set_cargo_path(self):
    env = os.environ.copy()
    self.context.products.safe_create_data('cargo_env', lambda: {})
    cargo_env = self.context.products.get_data('cargo_env')
    cargo_env['PATH'] = os.path.join(env['HOME'], '.cargo/bin')

  def execute(self):
    self.context.log.debug('Check if rust toolchain exist.')
    if self.check_if_rustup_exist():
      self.context.log.debug('Toolchain is already installed.')
    else:
      self.context.log.info('Toolchain is missing.\nInstalling toolchain...')
      self.setup_rustup()

    self.set_cargo_path()
    self.setup_toolchain()
