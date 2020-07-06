# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.goal.run_tracker import RunTracker
from pants.process.subprocess import Subprocess
from pants.reporting.reporting import Reporting
from pants.scm.subsystems.changed import Changed


class GlobalSubsystems:
    @classmethod
    def get(cls):
        """Subsystems used outside of any task."""
        return {Reporting, RunTracker, Changed, Subprocess.Factory}
