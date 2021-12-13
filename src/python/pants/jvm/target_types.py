# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from abc import ABCMeta

from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    FieldSet,
    SingleSourceField,
    StringField,
    StringSequenceField,
    Target,
)
from pants.util.docutil import git_url

# -----------------------------------------------------------------------------------------------
# `jvm_artifact` targets
# -----------------------------------------------------------------------------------------------

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


class JvmArtifactUrlField(StringField):
    alias = "url"
    required = False
    help = (
        "A URL that points to the location of this artifact. If specified, Pants will not fetch this artifact "
        "from default maven repositories, and instead fetch the artifact from this URL. To use default maven "
        "repositories, do not set this value. \n\nNote that `file:` URLs are not supported due to Pants' "
        "sandboxing feature. To use a local `JAR` file, use the `jar` field instead."
    )


class JvmArtifactJarSourceField(SingleSourceField):
    alias = "jar"
    expected_file_extensions = (".jar",)
    required = False
    help = "A JAR file that provides this artifact to the lockfile resolver, instead of a maven repository."


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


class JvmProvidesTypesField(StringSequenceField):
    alias = "experimental_provides_types"
    help = (
        "Signals that the specified types should be fulfilled by these source files during "
        "dependency inference. This allows for specific types within packages that are otherwise "
        "inferred as belonging to `jvm_artifact` targets to be unambiguously inferred as belonging "
        "to this first-party source. If a given type is defined, at least one source file captured "
        "by this target must actually provide that symbol."
    )


class JvmArtifactFieldSet(FieldSet):

    group: JvmArtifactGroupField
    artifact: JvmArtifactArtifactField
    version: JvmArtifactVersionField
    packages: JvmArtifactPackagesField
    url: JvmArtifactUrlField

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
        JvmArtifactUrlField,  # TODO: should `JvmArtifactFieldSet` have an `all_fields` field?
        JvmArtifactJarSourceField,
    )
    help = (
        "Represents a third-party JVM artifact as identified by its Maven-compatible coordinate, "
        "that is, its `group`, `artifact`, and `version` components."
    )


# -----------------------------------------------------------------------------------------------
# JUnit test support field(s)
# -----------------------------------------------------------------------------------------------


class JunitTestSourceField(SingleSourceField, metaclass=ABCMeta):
    """A marker that indicates that a source field represents a JUnit test."""


# -----------------------------------------------------------------------------------------------
# Generic resolve support fields
# -----------------------------------------------------------------------------------------------


class JvmCompatibleResolveNamesField(StringSequenceField):
    alias = "compatible_resolves"
    required = False
    help = (
        "The set of resolve names that this target is compatible with. Any targets which depend on "
        "one another must have at least one compatible resolve in common. Which resolves are actually "
        "used in a build is calculated based on a target's dependees."
    )


class JvmResolveNameField(StringField):
    alias = "resolve"
    required = False
    help = (
        "The name of the resolve to use when building this target. The name must be defined as "
        "one of the resolves in `--jvm-resolves`. If not supplied, the default resolve will be "
        "used, otherwise, one resolve that is compatible with all dependency targets will be used."
    )
