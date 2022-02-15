# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.helm.test.unittest import rules as test
from pants.backend.helm.test.unittest.subsystem import rules as subsystem_rules
from pants.backend.helm.test.unittest.target_types import HelmUnitTestsTarget


def target_types():
    return [HelmUnitTestsTarget]


def rules():
    return [*subsystem_rules(), *test.rules()]
