# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os

from pants.base.workunit import WorkUnit, WorkUnitLabel
from pants.util.dirutil import safe_mkdir

from pants.contrib.rust.tasks.cargo_task import CargoTask


class Fetch(CargoTask):
  @classmethod
  def prepare(cls, options, round_manager):
    super(Fetch, cls).prepare(options, round_manager)
    round_manager.require_data('cargo_env')

  @classmethod
  def implementation_version(cls):
    return super(Fetch, cls).implementation_version() + [('Cargo_Fetch', 1)]

  def create_cargo_home(self):
    cargo_home_path = os.path.join(self.versioned_workdir, 'cargo_home')
    self.context.log.debug('Creating Cargo home in: {0}'.format(cargo_home_path))
    safe_mkdir(cargo_home_path)
    return cargo_home_path

  def fetch(self, target):
    with self.context.new_workunit(name='fetch', labels=[WorkUnitLabel.TOOL]) as workunit:
      abs_manifest_path = os.path.join(target.manifest, self.manifest_name())

      self.context.log.debug('Fetching dependencies for {0}'.format(abs_manifest_path))

      cmd = ['cargo', 'fetch', '--manifest-path', abs_manifest_path]

      env = {
        'CARGO_HOME': (self.context.products.get_data('cargo_env')['CARGO_HOME'], False),
        'PATH': (self.context.products.get_data('cargo_env')['PATH'], True)
      }

      self.run_command(cmd, target.manifest, env, workunit)

      if workunit.outcome() != WorkUnit.SUCCESS:
        self.context.log.error(workunit.outcome_string(workunit.outcome()))
      else:
        self.context.log.debug(workunit.outcome_string(workunit.outcome()))

  def set_cargo_home(self, cargo_home):
    cargo_env = self.context.products.get_data('cargo_env')
    cargo_env['CARGO_HOME'] = cargo_home

  def create_and_set_cargo_home(self):
    cargo_home = self.create_cargo_home()
    self.set_cargo_home(cargo_home)

  def execute(self):
    self.create_and_set_cargo_home()

    workspace_targets = self.get_targets(self.is_cargo_original_workspace)
    for member in workspace_targets:
      self.fetch(member)
