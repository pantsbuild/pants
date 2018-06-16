# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.goal.task_registrar import TaskRegistrar as task

from pants.contrib.native.subsystems.native_toolchain import create_native_toolchain_rules
from pants.contrib.native.tasks.populate_native_environment import PopulateNativeEnvironment


def register_goals():
  task(name='populate-native-environment', action=PopulateNativeEnvironment).install('bootstrap')


def rules():
  return create_native_toolchain_rules()
