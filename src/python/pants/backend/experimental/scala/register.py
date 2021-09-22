# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from pants.backend.scala.target_types import ScalaArtifactTarget
from pants.backend.scala.target_types import rules as target_types_rules
from pants.jvm.target_types import JvmArtifact, JvmDependencyLockfile


def target_types():
    return [ScalaArtifactTarget, JvmDependencyLockfile, JvmArtifact]


def rules():
    return [
        *target_types_rules(),
    ]
