# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os

from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.util.contextutil import temporary_dir
from pants_test.task_test_base import TaskTestBase

from pants.contrib.rust.tasks.cargo_toolchain import Toolchain


class CargoTaskToolchain(TaskTestBase):
  @classmethod
  def task_type(cls):
    return Toolchain

  def test_download_rustup_install_script(self):
    task = self.create_task(self.context())
    install_script = task.download_rustup_install_script()
    self.assertNotEqual("", install_script.text)

  def test_check_integrity_of_rustup_install_script_failure(self):
    task = self.create_task(self.context())
    with self.assertRaises(TaskError):
      task.check_integrity_of_rustup_install_script('test')

  def test_set_cargo_path(self):
    context = self.context()
    task = self.create_task(context)
    task.set_cargo_path()
    env = os.environ.copy()
    result = os.path.join(env['HOME'], '.cargo/bin')
    self.assertEqual(result, context.products.get_data('cargo_env')['PATH'])

  def test_save_rustup_install_script(self):
    task = self.create_task(self.context())
    task.save_rustup_install_script('test')
    script_path = os.path.join(task.versioned_workdir, 'rustup_install_script', 'rustup.sh')
    self.assertTrue(os.path.isfile(script_path))
    with open(script_path, 'r') as fp:
      script_content = fp.read()
    self.assertEqual('test', script_content)

  def test_get_toolchain(self):
    task = self.create_task(
      self.context(options={'test_scope': {'toolchain': 'nightly-toolchain'}}))
    toolchain = task.get_toolchain()
    self.assertEqual('nightly-toolchain', toolchain)

  def test_get_toolchain_file(self):
    with temporary_dir(root_dir=get_buildroot()) as chroot:
      rust_toolchain = os.path.join(chroot, 'rust-toolchain')
      with open(rust_toolchain, 'w') as fp:
        fp.write('nightly-toolchain')

      dir_base = os.path.basename(chroot)
      task = self.create_task(self.context(options={'test_scope': {'toolchain': dir_base}}))
      toolchain = task.get_toolchain()
      self.assertEqual('nightly-toolchain', toolchain)

  # def setup_rustup(self):
  # def install_rust_toolchain(self, toolchain):
  # def check_if_rustup_exist(self):
  # def try_to_find_rustup_executable(self):
  # def try_to_find_rustup_executable_in_default_location(self):
  # def setup_toolchain(self):
