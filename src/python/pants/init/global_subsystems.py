# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


from pants.binaries.binary_util import BinaryUtil
from pants.goal.run_tracker import RunTracker
from pants.init.repro import Reproducer
from pants.process.subprocess import Subprocess
from pants.reporting.reporting import Reporting
from pants.reporting.workunits import Workunits
from pants.scm.subsystems.changed import Changed
from pants.source.source_root import SourceRootConfig


class GlobalSubsystems:
  @classmethod
  def get(cls):
    """Subsystems used outside of any task."""
    return {
      SourceRootConfig,
      Reporting,
      Reproducer,
      RunTracker,
      Changed,
      Workunits,
      BinaryUtil.Factory,
      Subprocess.Factory
    }
