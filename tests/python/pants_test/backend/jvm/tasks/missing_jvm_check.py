# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.java.distribution.distribution import DistributionLocator
from pants.testutil.subsystem.util import init_subsystem


def is_missing_jvm(version):
    init_subsystem(DistributionLocator)
    try:
        DistributionLocator.cached(minimum_version=version, maximum_version=f"{version}.9999")
        return False
    except DistributionLocator.Error:
        return True
