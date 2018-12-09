# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants.backend.cargo_bootstrap.subsystems.rustup import CargoInstallation, Rustup
from pants.backend.cargo_bootstrap.targets.cargo_dist import CargoDist
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnit, WorkUnitLabel
from pants.task.task import Task
from pants.util.collections import assert_single_element
from pants.util.memo import memoized_property
from pants.util.process_handler import subprocess


class BootstrapCargo(Task):

  @classmethod
  def subsystem_dependencies(cls):
    return super(BootstrapCargo, cls).subsystem_dependencies() + (Rustup.scoped(cls),)

  @memoized_property
  def _rustup(self):
    return Rustup.scoped_instance(self)

  # TODO(#5869): delete this when we can request Subsystems from options in tasks!
  def _request_single(self, product, subject):
    # NB: This is not supposed to be exposed to Tasks yet -- see #4769 to track the status of
    # exposing v2 products in v1 tasks.
    return self.context._scheduler.product_request(product, [subject])[0]

  @memoized_property
  def _cargo_installation(self):
    return self._request_single(CargoInstallation, self._rustup)

  class CargoBootstrapError(TaskError): pass

  def execute(self):
    cargo_dist = assert_single_element(self.context.targets(lambda t: isinstance(t, CargoDist)))

    with self.invalidated([cargo_dist]) as invalidation_check:
      if invalidation_check.invalid_vts:
        cargo_dist_vt = assert_single_element(invalidation_check.invalid_vts)
        with self.context.new_workunit('bootstrap-native-engine',
                                       labels=[WorkUnitLabel.BOOTSTRAP]) as workunit:
          cargo_toml = 'src/rust/engine/Cargo.toml'
          if not cargo_toml in cargo_dist_vt.target.sources_relative_to_buildroot():
            raise self.CargoBootstrapError('???: {}'.format(cargo_toml))
          try:
            subprocess.check_call(
              ['cargo', 'build',
               '--manifest-path', cargo_toml,
               '-p', 'engine'],
              stdout=workunit.output('stdout'),
              stderr=workunit.output('stderr'),
              env=self._cargo_installation.cargo_exec_env(),
            )
          except OSError as e:
            workunit.set_outcome(WorkUnit.FAILURE)
            raise self.CargoBootstrapError('???')
          workunit.set_outcome(WorkUnit.SUCCESS)
