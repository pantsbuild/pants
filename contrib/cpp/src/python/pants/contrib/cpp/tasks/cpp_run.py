# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.base.workunit import WorkUnitLabel

from pants.contrib.cpp.targets.cpp_binary import CppBinary
from pants.contrib.cpp.tasks.cpp_task import CppTask


class CppRun(CppTask):
    """Runs a C++ binary."""

    @classmethod
    def supports_passthru_args(cls):
        return True

    @classmethod
    def prepare(cls, options, round_manager):
        super().prepare(options, round_manager)
        # Require that an executable has been built.
        round_manager.require_data("exe")

    def execute(self):
        binary_target = self.require_single_root_target()
        if isinstance(binary_target, CppBinary):
            with self.context.new_workunit(name="cpp-run", labels=[WorkUnitLabel.RUN]) as workunit:
                cmd = [
                    self.context.products.get_only("exe", binary_target),
                    *self.get_passthru_args(),
                    *self.get_options().args,
                ]
                self.run_command(cmd, workunit)
