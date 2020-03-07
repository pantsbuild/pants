# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.task.fmt_task_mixin import FmtTaskMixin

from pants.contrib.go.subsystems.gofmt import Gofmt
from pants.contrib.go.tasks.go_fmt_task_base import GoFmtTaskBase


class GoFmt(FmtTaskMixin, GoFmtTaskBase):
    """Format Go code using gofmt."""

    @property
    def skip_execution(self):
        return super().determine_if_skipped(formatter_subsystem=Gofmt.global_instance())

    def execute(self):
        with self.go_fmt_invalid_targets(["-w"]) as output:
            if output:
                self.context.logger.info(output)
