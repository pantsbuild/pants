# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.jvm.tasks.nailgun_task import NailgunTask
from pants.base.workunit import WorkUnitLabel
from pants.goal.task_registrar import TaskRegistrar as task


def register_goals():
    task(name="run-workunit-label-test", action=TestWorkUnitLabelTask).install()


class TestWorkUnitLabelTask(NailgunTask):
    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register("--ignore-label", default=False, type=bool)

    def execute(self):
        labels = [WorkUnitLabel.COMPILER]
        if self.get_options().ignore_label:
            labels.append(WorkUnitLabel.SUPPRESS_LABEL)

        with self.context.new_workunit("dummy_workunit"):
            self.runjava(
                classpath=[],
                main="non-existent-main-class",
                args=["-version"],
                workunit_labels=labels,
            )
