# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.java import tailor
from pants.backend.java.compile import javac, javac_binary
from pants.backend.java.target_types import (
    JavaSource,
    JavaSourcesGeneratorTarget,
    JunitTestsGeneratorTarget,
    JunitTestTarget,
)
from pants.backend.java.target_types import rules as target_types_rules
from pants.backend.java.test import junit
from pants.jvm import util_rules
from pants.jvm.goals import coursier
from pants.jvm.resolve import coursier_fetch, coursier_setup
from pants.jvm.target_types import JvmDependencyLockfile


def target_types():
    return [
        JunitTestTarget,
        JunitTestsGeneratorTarget,
        JavaSource,
        JavaSourcesGeneratorTarget,
        JvmDependencyLockfile,
    ]


def rules():
    return [
        *javac.rules(),
        *javac_binary.rules(),
        *junit.rules(),
        *coursier.rules(),
        *coursier_fetch.rules(),
        *coursier_setup.rules(),
        *tailor.rules(),
        *util_rules.rules(),
        *target_types_rules(),
    ]
