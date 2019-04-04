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
from pants.base.workunit import WorkUnitLabel
from pants.util.dirutil import chmod_plus_x, read_file, safe_file_dump, safe_mkdir

from pants.contrib.rust.tasks.cargo_task import CargoTask


class Toolchain(CargoTask):

  @classmethod
  def register_options(cls, register):
    super(Toolchain, cls).register_options(register)
    register('--toolchain', type=str, default='nightly-2018-12-31', help='Toolchain')
    register(
        '--script_fingerprint',
        type=str,
        default='a741519217f27635fe49004764969cfac20fbce744d20b7114600012e6e80796',
        help='The sha256 hash of the rustup install script (https://sh.rustup.rs).')

  @classmethod
  def product_types(cls):
    return ['cargo_env', 'cargo_toolchain']

  @classmethod
  def implementation_version(cls):
    return super(Toolchain, cls).implementation_version() + [('Cargo_Toolchain', 1)]

  def setup_rustup(self):
    self.context.log.info('Installing rustup...')
    install_script = self.download_rustup_install_script()
    self.check_integrity_of_rustup_install_script(install_script.text)
    install_script_dir_path, install_script_file_path = self.save_rustup_install_script(
        install_script.text)

    cmd = [install_script_file_path, '-y']  # -y Disable confirmation prompt.

    returncode = self.execute_command(
        cmd, 'setup-rustup', [WorkUnitLabel.BOOTSTRAP], current_working_dir=install_script_dir_path)

    if returncode != 0:
      raise TaskError('Cannot install rustup.')

  def download_rustup_install_script(self):
    return requests.get('https://sh.rustup.rs')

  def check_integrity_of_rustup_install_script(self, install_script):
    hasher = hashlib.sha256(install_script.encode('utf-8'))
    current_fingerprint = hasher.hexdigest() if PY3 else hasher.hexdigest().decode('utf-8')
    if current_fingerprint != self.get_options().script_fingerprint:
      raise TaskError(
          'The fingerprint of the rustup script has changed!\nLast known: {0}\ncurrent: {1}'.format(
              self.get_options().script_fingerprint, current_fingerprint))

  def save_rustup_install_script(self, install_script):
    save_dir_path = os.path.join(self.versioned_workdir, 'rustup_install_script')
    safe_mkdir(save_dir_path, clean=True)
    save_file_path = os.path.join(save_dir_path, 'rustup.sh')
    self.context.log.debug('Save rustup.sh in {}'.format(save_file_path))
    safe_file_dump(save_file_path, install_script, mode='w')
    chmod_plus_x(save_file_path)
    return save_dir_path, save_file_path

  def install_rust_toolchain(self, toolchain):
    self.context.log.debug('Installing toolchain: {0}'.format(toolchain))

    cmd = ['rustup', 'install', toolchain]

    env = {'PATH': (self.context.products.get_data('cargo_env')['PATH'], True)}

    returncode = self.execute_command(
        cmd, 'install-rustup-toolchain', [WorkUnitLabel.BOOTSTRAP], env_vars=env)

    if returncode != 0:
      raise TaskError('Cannot install toolchain: {}'.format(toolchain))

  def check_if_rustup_exist(self):
    # If the rustup executable can't be find via the path variable,
    # try to find it in the default location.

    return self.try_to_find_rustup_executable(
    ) or self.try_to_find_rustup_executable_in_default_location()

  def try_to_find_rustup_executable(self):
    return distutils.spawn.find_executable('rustup') is not None

  def try_to_find_rustup_executable_in_default_location(self):
    env = os.environ.copy()
    default_rustup_location = os.path.join(env['HOME'], '.cargo/bin', 'rustup')
    if os.path.isfile(default_rustup_location):
      self.context.log.debug('Found rustup in default location')
      return True
    else:
      return False

  def setup_toolchain(self):
    toolchain = self.get_toolchain()
    self.install_rust_toolchain(toolchain)
    self.context.products.safe_create_data('cargo_toolchain', lambda: toolchain)

  def set_cargo_path(self):
    env = os.environ.copy()
    self.context.products.safe_create_data('cargo_env', lambda: {})
    cargo_env = self.context.products.get_data('cargo_env')
    cargo_env['PATH'] = os.path.join(env['HOME'], '.cargo/bin')

  def get_toolchain(self):
    toolchain_opt = self.get_options().toolchain
    toolchain_path = os.path.join(get_buildroot(), toolchain_opt, 'rust-toolchain')
    if os.path.isfile(toolchain_path):
      self.context.log.debug('Found rust-toolchain file.')
      toolchain = read_file(toolchain_path, binary_mode=False)
      return toolchain.strip()
    else:
      return toolchain_opt

  def execute(self):
    self.context.log.debug('Check if rustup exist.')
    if self.check_if_rustup_exist():
      self.context.log.debug('Rustup is already installed.')
    else:
      self.context.log.info('Rustup is missing.')
      self.setup_rustup()

    self.set_cargo_path()
    self.setup_toolchain()
