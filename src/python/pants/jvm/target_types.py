# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    FieldSet,
    SingleSourceField,
    SpecialCasedDependencies,
    StringField,
    StringSequenceField,
    Target,
)
from pants.util.docutil import git_url

_DEFAULT_PACKAGE_MAPPING_URL = git_url(
    "src/python/pants/jvm/dependency_inference/jvm_artifact_mappings.py"
)


class JvmArtifactGroupField(StringField):
    alias = "group"
    required = True
    help = (
        "The 'group' part of a Maven-compatible coordinate to a third-party jar artifact. For the jar coordinate "
        "com.google.guava:guava:30.1.1-jre, the group is 'com.google.guava'."
    )


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


class JvmArtifactPackagesField(StringSequenceField):
    alias = "packages"
    help = (
        "The JVM packages this artifact provides for the purposes of dependency inference.\n\n"
        'For example, the JVM artifact `junit:junit` might provide `["org.junit.**"]`.\n\n'
        "Usually you can leave this field off. If unspecified, Pants will fall back to the "
        "`[java-infer].third_party_import_mapping`, then to a built in mapping "
        f"({_DEFAULT_PACKAGE_MAPPING_URL}), and then finally it will default to "
        "the normalized `group` of the artifact. For example, in the absence of any other mapping "
        "the artifact `io.confluent:common-config` would default to providing "
        '`["io.confluent.**"]`.\n\n'
        "The package path may be made recursive to match symbols in subpackages "
        'by adding `.**` to the end of the package path. For example, specify `["org.junit.**"]` '
        "to infer a dependency on the artifact for any file importing a symbol from `org.junit` or "
        "its subpackages."
    )


class JvmArtifactFieldSet(FieldSet):

    group: JvmArtifactGroupField
    artifact: JvmArtifactArtifactField
    version: JvmArtifactVersionField
    packages: JvmArtifactPackagesField

    required_fields = (
        JvmArtifactGroupField,
        JvmArtifactArtifactField,
        JvmArtifactVersionField,
        JvmArtifactPackagesField,
    )


class JvmArtifact(Target):
    alias = "jvm_artifact"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        *JvmArtifactFieldSet.required_fields,
    )
    help = (
        "Represents a third-party JVM artifact as identified by its Maven-compatible coordinate, "
        "that is, its `group`, `artifact`, and `version` components."
    )


class JvmCompatibleResolveNamesField(StringSequenceField):
    alias = "compatible_resolves"
    required = False
    help = (
        "The set of resolve names that this target is compatible with. Any targets which depend on "
        "one another must have at least one compatible resolve in common. Which resolves are actually "
        "used in a build is calculated based on a target's dependees."
    )


class JvmResolveName(StringField):
    alias = "resolve"
    required = False
    help = (
        "The name of the resolve to use when building this target. The name must be defined as "
        "one of the resolves in `--jvm-resolves`. If not supplied, the default resolve will be "
        "used, otherwise, one resolve that is compatible with all dependency targets will be used."
    )


class JvmRequirementsField(SpecialCasedDependencies):
    alias = "requirements"
    required = True
    help = (
        "A sequence of addresses to targets compatible with `jvm_artifact` that specify the coordinates for "
        "third-party JVM dependencies."
    )


class JvmLockfileSources(SingleSourceField):
    expected_file_extensions = (".lockfile",)
    # Expect 0 or 1 files.
    expected_num_files = range(0, 2)
    required = False
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
    core_fields = (
        *COMMON_TARGET_FIELDS,
        JvmLockfileSources,
    )
    help = "A Coursier lockfile along with references to the artifacts to use for the lockfile."
