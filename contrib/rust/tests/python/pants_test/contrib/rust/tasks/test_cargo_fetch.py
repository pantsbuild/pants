# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os
from textwrap import dedent

from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.util.dirutil import safe_mkdir
from pants_test.task_test_base import TaskTestBase

from pants.contrib.rust.targets.original.cargo_library import CargoLibrary
from pants.contrib.rust.tasks.cargo_fetch import Fetch


class CargoTaskFetch(TaskTestBase):
  @classmethod
  def task_type(cls):
    return Fetch

  def test_create_cargo_home(self):
    task = self.create_task(self.context())
    cargo_home_test = task.create_cargo_home()

    cargo_home = os.path.join(task.versioned_workdir, 'cargo_home')
    self.assertEqual(cargo_home, cargo_home_test)
    self.assertTrue(os.path.isdir(cargo_home))

  def test_set_cargo_home(self):
    context = self.context()
    context.products.safe_create_data('cargo_env', lambda: {})
    task = self.create_task(context)
    cargo_home = os.path.join(task.versioned_workdir, 'cargo_home')
    task.set_cargo_home(cargo_home)
    self.assertEqual(cargo_home, context.products.get_data('cargo_env')['CARGO_HOME'])

  def create_cargo_lib_project(self, name):
    project_path = os.path.join(get_buildroot(), name)
    safe_mkdir(project_path)

    src_path = os.path.join(project_path, 'src')
    safe_mkdir(src_path)

    self.create_file(os.path.join(name, 'BUILD'), contents=dedent("""       
          # Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
          # Licensed under the Apache License, Version 2.0 (see LICENSE).
  
          cargo_library(
            name='{name}',
            sources=rglobs('*.rs', 'Cargo.toml', exclude=[rglobs('**/target/*.rs')]),
          )
          """).format(name=name).strip())

    self.create_file(os.path.join(name, 'Cargo.toml'), contents=dedent("""       
          [package]
          name = "{name}"
          version = "0.1.0"
          authors = ["Pants Build <pantsbuild@gmail.com>"]
          edition = "2018"
          
          [dependencies]
          sha2 = "0.8"
          """).format(name=name).strip())

    self.create_file(os.path.join(name, 'src', 'lib.rs'), contents=dedent("""       
          #[cfg(test)]
          mod tests {
              #[test]
              fn it_works() {
                  assert_eq!(2 + 2, 4);
              }
              #[test]
              fn it_works_2() {
                  assert_eq!(2 + 1 + 1, 4);
              }
          }
          """).strip())

    with open(os.path.join(project_path, 'Cargo.toml'), 'r') as fp:
      print(fp.read())

  def test_fetch(self):
    project_name = 'test'
    self.create_cargo_lib_project(project_name)
    t1 = self.make_target(spec=project_name, target_type=CargoLibrary)

    context = self.context()
    task = self.create_task(context)

    cargo_home = os.path.join(task.versioned_workdir, 'cargo_home')
    safe_mkdir(cargo_home)

    env = os.environ.copy()
    cargo_path = os.path.join(env['HOME'], '.cargo/bin')
    context.products.safe_create_data('cargo_env',
                                      lambda: {'CARGO_HOME': cargo_home, 'PATH': cargo_path})
    context.products.safe_create_data('cargo_toolchain', lambda: 'nightly-2018-12-31')

    cargo_git = os.path.join(cargo_home, 'git')
    cargo_registry = os.path.join(cargo_home, 'registry')

    self.assertFalse(os.path.isdir(cargo_git))
    self.assertFalse(os.path.isdir(cargo_registry))

    task.fetch(t1)

    self.assertTrue(os.path.isdir(cargo_registry))

  def test_fetch_failure(self):
    project_name = 'test'
    self.create_cargo_lib_project(project_name)
    t1 = self.make_target(spec=project_name, target_type=CargoLibrary)

    context = self.context()
    task = self.create_task(context)

    cargo_home = os.path.join(task.versioned_workdir, 'cargo_home')
    safe_mkdir(cargo_home)

    env = os.environ.copy()
    cargo_path = os.path.join(env['HOME'], '.cargo/bin')
    context.products.safe_create_data('cargo_env',
                                      lambda: {'CARGO_HOME': cargo_home, 'PATH': cargo_path})
    context.products.safe_create_data('cargo_toolchain', lambda: 'XYZ')

    with self.assertRaises(TaskError):
      task.fetch(t1)
