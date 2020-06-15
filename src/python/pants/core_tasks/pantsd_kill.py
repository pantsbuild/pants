# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.base.exceptions import TaskError
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.pantsd.pants_daemon_client import PantsDaemonClient
from pants.pantsd.process_manager import ProcessManager
from pants.task.task import Task


class PantsDaemonKill(Task):
    """Terminate the pants daemon."""

    def execute(self):
        try:
            pantsd_client = PantsDaemonClient(OptionsBootstrapper.create().bootstrap_options)
            with pantsd_client.lifecycle_lock:
                pantsd_client.terminate()
        except ProcessManager.NonResponsiveProcess as e:
            raise TaskError("failure while terminating pantsd: {}".format(e))
