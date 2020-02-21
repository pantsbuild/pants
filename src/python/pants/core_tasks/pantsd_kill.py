# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.base.exceptions import TaskError
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.pantsd.pants_daemon import PantsDaemon
from pants.pantsd.process_manager import ProcessManager
from pants.task.task import Task


class PantsDaemonKill(Task):
    """Terminate the pants daemon."""

    def execute(self):
        try:
            pantsd = PantsDaemon.Factory.create(OptionsBootstrapper.create(), full_init=False)
            with pantsd.lifecycle_lock:
                pantsd.terminate()
        except ProcessManager.NonResponsiveProcess as e:
            raise TaskError("failure while terminating pantsd: {}".format(e))
