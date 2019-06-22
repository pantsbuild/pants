# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.goal.task_registrar import TaskRegistrar as task

from pants.contrib.findbugs.tasks.findbugs import FindBugs


def register_goals():
  task(name='findbugs', action=FindBugs).install('compile')
