# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from pants.engine.rules import collect_rules
from pants.engine.target import COMMON_TARGET_FIELDS
from pants.jvm.target_types import (
    JvmArtifact,
    JvmArtifactArtifactField,
    JvmArtifactGroupField,
    JvmArtifactVersionField,
)

# -----------------------------------------------------------------------------------------------
# `scala_artifact` target type
# -----------------------------------------------------------------------------------------------


class ScalaArtifactArtifactField(JvmArtifactArtifactField):
    # TODO: Find a way to have `compute_value` append value of `ScalaSubsystem.version`. Or maybe make
    #  JvmArtifactArtifactField into an async field?
    pass


class ScalaArtifactTarget(JvmArtifact):
    alias = "scala_artifact"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        JvmArtifactGroupField,
        ScalaArtifactArtifactField,
        JvmArtifactVersionField,
    )
    help = (
        "Represents a third-party Scala artifact as identified by its Maven-compatible coordinate, "
        "that is, its `group`, `artifact`, and `version` components. The Scala version suffix will "
        "be appended automatically to the `artifact` field."
    )


def rules():
    return collect_rules()
