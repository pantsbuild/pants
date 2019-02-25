# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os
import shutil

from pants.base.build_environment import get_buildroot
from pants.base.workunit import WorkUnit, WorkUnitLabel

from pants.contrib.rust.tasks.cargo_task import CargoTask


class Test(CargoTask):
  @classmethod
  def prepare(cls, options, round_manager):
    super(Test, cls).prepare(options, round_manager)
    round_manager.require_data('rust_tests')

  @classmethod
  def implementation_version(cls):
    return super(Test, cls).implementation_version() + [('Cargo_Test', 1)]

  def maybe_copy_tests(self, test_definitions):
    result_dir = self.versioned_workdir

    for definition in test_definitions:
      test_path, test_cwd = definition
      if os.path.isfile(test_path) and not os.path.isfile(
              os.path.join(result_dir, os.path.basename(test_path))):
        self.context.log.info(
          'Copy: {0}\n\tto: {1}'.format(os.path.relpath(test_path, get_buildroot()),
                                        os.path.relpath(result_dir, get_buildroot())))
        shutil.copy(test_path, result_dir)

  def run_test(self, test_path, cwd):
    with self.context.new_workunit(name='run-test', labels=[WorkUnitLabel.TEST]) as workunit:
      self.run_command(test_path, cwd, {}, workunit)

      if workunit.outcome() != WorkUnit.SUCCESS:
        self.context.log.error(workunit.outcome_string(workunit.outcome()))
      else:
        self.context.log.info(workunit.outcome_string(workunit.outcome()))

  def run_tests(self, test_definitions):
    result_dir = self.versioned_workdir

    for definition in test_definitions:
      test_path, test_cwd = definition
      test_path = os.path.join(result_dir, os.path.basename(test_path))
      if os.path.isfile(test_path):
        self.run_test(test_path, test_cwd)

  def execute(self):
    test_targets = self.context.products.get_data('rust_tests')

    for test_definitions in test_targets.values():
      self.maybe_copy_tests(test_definitions)
      self.run_tests(test_definitions)
