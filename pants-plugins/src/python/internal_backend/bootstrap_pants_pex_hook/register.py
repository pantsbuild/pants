# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from internal_backend.bootstrap_pants_pex_hook.bootstrap_pants_pex import BootstrapPantsPex
from pants.goal.task_registrar import TaskRegistrar as task


def register_goals():
  task(name='prepare-pants-pex', action=BootstrapPantsPex).install('test', before="pytest-prep")
