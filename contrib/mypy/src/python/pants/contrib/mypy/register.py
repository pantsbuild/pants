# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.goal.task_registrar import TaskRegistrar as task

from pants.contrib.mypy.tasks.mypy_task import MypyTask


class MypyStandalone(MypyTask):
    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register("--skip", type=bool, default=False, help="Skip running mypy.")
        register(
            "--transitive",
            type=bool,
            default=False,
            help="Whether to run mypy on transitive dependencies of the given python targets.",
        )


def register_goals():
    task(name="mypy", action=MypyTask).install("lint")
    task(name="mypy", action=MypyStandalone).install()
