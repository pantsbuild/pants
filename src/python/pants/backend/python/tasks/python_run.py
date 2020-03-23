# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import signal

from pants.backend.python.targets.python_binary import PythonBinary
from pants.backend.python.tasks.python_execution_task_base import PythonExecutionTaskBase
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnitLabel
from pants.util.osutil import safe_kill


class PythonRun(PythonExecutionTaskBase):
    """Run a Python executable."""

    @classmethod
    def supports_passthru_args(cls):
        return True

    def execute(self):
        binary = self.require_single_root_target()
        if isinstance(binary, PythonBinary):
            # We can't throw if binary isn't a PythonBinary, because perhaps we were called on a
            # jvm_binary, in which case we have to no-op and let jvm_run do its thing.
            # TODO(benjy): Use MutexTask to coordinate this.

            pex = self.create_pex(binary.pexinfo)
            args = [*self.get_passthru_args(), *self.get_options().args]

            env = self.prepare_pex_env()

            self.context.release_lock()
            cmdline = " ".join(pex.cmdline(args))
            with self.context.new_workunit(
                name="run", cmd=cmdline, labels=[WorkUnitLabel.TOOL, WorkUnitLabel.RUN]
            ):
                po = pex.run(blocking=False, args=args, env=env)
                try:
                    result = po.wait()
                    if result != 0:
                        msg = f"{cmdline} ... exited non-zero ({result})"
                        raise TaskError(msg, exit_code=result)
                except KeyboardInterrupt:
                    # The process may still have exited, even if we were interrupted.
                    safe_kill(po.pid, signal.SIGINT)
                    raise
