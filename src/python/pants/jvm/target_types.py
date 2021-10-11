# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    MultipleSourcesField,
    SpecialCasedDependencies,
    StringField,
    Target,
)


class JvmArtifactGroupField(StringField):
    alias = "group"
    help = (
        "The 'group' part of a Maven-compatible coordinate to a third-party jar artifact. For the jar coordinate "
        "com.google.guava:guava:30.1.1-jre, the group is 'com.google.guava'."
    )
    required = True


class JvmArtifactArtifactField(StringField):
    alias = "artifact"
    required = True
    help = (
        "The 'artifact' part of a Maven-compatible coordinate to a third-party jar artifact. For the jar coordinate "
        "com.google.guava:guava:30.1.1-jre, the artifact is 'guava'."
    )


class JvmArtifactVersionField(StringField):
    alias = "version"
    required = True
    help = (
        "The 'version' part of a Maven-compatible coordinate to a third-party jar artifact. For the jar coordinate "
        "com.google.guava:guava:30.1.1-jre, the version is '30.1.1-jre'."
    )


class JvmArtifact(Target):
    alias = "jvm_artifact"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        JvmArtifactGroupField,
        JvmArtifactArtifactField,
        JvmArtifactVersionField,
    )
    help = (
        "Represents a third-party JVM artifact as identified by its Maven-compatible coordinate, "
        "that is, its `group`, `artifact`, and `version` components."
    )


class JvmRequirementsField(SpecialCasedDependencies):
    alias = "requirements"
    required = True
    help = (
        "A sequence of addresses to targets compatible with `jvm_artifact` that specify the coordinates for "
        "third-party JVM dependencies."
    )


class JvmLockfileSources(MultipleSourcesField):
    expected_file_extensions = (".lockfile",)
    expected_num_files = range(
        2
    )  # NOTE: This actually means 0 or 1 files; `range`'s end is noninclusive.
    help = (
        "A single Pants Coursier Lockfile source.\n\n"
        "Use `./pants coursier-resolve ...` to generate (or regenerate) the Lockfile."
        " If the Lockfile doesn't exist on disk, the first run of `coursier-resolve` will attempt"
        " to generate it for you to the default file name ('coursier_resolve.lockfile')."
        " After running `coursier-resolve` for the first time, you should update this field's"
        "`sources` to explicit take ownership of the generated lockfile."
    )


class JvmDependencyLockfile(Target):
    alias = "coursier_lockfile"
    core_fields = (*COMMON_TARGET_FIELDS, JvmLockfileSources, JvmRequirementsField)
    help = "A Coursier lockfile along with references to the artifacts to use for the lockfile."
