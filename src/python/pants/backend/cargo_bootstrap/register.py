# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants.backend.cargo_bootstrap.subsystems.rustup import Rustup, rustup_rules
from pants.backend.cargo_bootstrap.targets.cargo_dist import CargoDist
from pants.backend.cargo_bootstrap.tasks.bootstrap_cargo import BootstrapCargo
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.goal.task_registrar import TaskRegistrar as task


def build_file_aliases():
  return BuildFileAliases(
    targets={
      CargoDist.alias: CargoDist,
    },
  )


def global_subsystems():
  return {Rustup}


def register_goals():
  task(name='bootstrap-cargo', action=BootstrapCargo).install('bootstrap-native-engine')


def rules():
  return rustup_rules()
