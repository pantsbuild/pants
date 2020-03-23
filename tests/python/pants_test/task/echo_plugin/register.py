# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

from pants.goal.goal import Goal
from pants.goal.task_registrar import TaskRegistrar as task
from pants.task.target_restriction_mixins import (
    HasSkipAndTransitiveGoalOptionsMixin,
    SkipAndTransitiveGoalOptionsRegistrar,
)
from pants.task.task import Task


class EchoTaskBase(HasSkipAndTransitiveGoalOptionsMixin, Task):
    goal_options_registrar_cls = SkipAndTransitiveGoalOptionsRegistrar
    prefix = None

    def execute(self):
        with open(os.path.join(self.workdir, "output"), "w") as fp:
            fp.write("\n".join(t.address.spec for t in self.get_targets()))


class EchoOne(EchoTaskBase):
    pass


class EchoTwo(EchoTaskBase):
    pass


def register_goals():
    Goal.register(
        "echo",
        "test tasks that echo their target set",
        options_registrar_cls=SkipAndTransitiveGoalOptionsRegistrar,
    )
    task(name="one", action=EchoOne).install("echo")
    task(name="two", action=EchoTwo).install("echo")
