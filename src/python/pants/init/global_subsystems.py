# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from builtins import object

from pants.binaries.binary_util import BinaryUtil
from pants.goal.run_tracker import RunTracker
from pants.init.repro import Reproducer
from pants.init.subprocess import Subprocess
from pants.reporting.reporting import Reporting
from pants.scm.subsystems.changed import Changed
from pants.source.source_root import SourceRootConfig


class GlobalSubsystems(object):
  @classmethod
  def get(cls):
    """Subsystems used outside of any task."""
    return {
      SourceRootConfig,
      Reporting,
      Reproducer,
      RunTracker,
      Changed,
      BinaryUtil.Factory,
      Subprocess.Factory
    }
