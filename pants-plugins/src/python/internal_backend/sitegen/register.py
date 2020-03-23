# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from internal_backend.sitegen.tasks.sitegen import SiteGen
from pants.goal.task_registrar import TaskRegistrar as task


def register_goals():
    task(name="sitegen", action=SiteGen).install()
