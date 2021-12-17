# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from abc import ABCMeta
from typing import Optional

from pants.engine.addresses import Address
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    FieldSet,
    InvalidFieldException,
    InvalidTargetException,
    SingleSourceField,
    StringField,
    StringSequenceField,
    Target,
)
from pants.util.docutil import git_url

# -----------------------------------------------------------------------------------------------
# Generic resolve support fields
# -----------------------------------------------------------------------------------------------


class JvmCompatibleResolvesField(StringSequenceField):
    alias = "compatible_resolves"
    required = False
    help = (
        "The set of resolve names that this target is compatible with.\n\n"
        "If not defined, will default to `[jvm].default_resolve`.\n\n"
        "Each name must be defined as a resolve in `[jvm].resolves`.\n\n"
        # TODO: Document expectations for dependencies once we validate that.
    )


class JvmResolveField(StringField):
    alias = "resolve"
    required = False
    help = (
        "The name of the resolve to use when building this target.\n\n"
        "If not defined, will default to `[jvm].default_resolve`.\n\n"
        "The name must be defined as a resolve in `[jvm].resolves`."
        # TODO: Document expectations for dependencies once we validate that.
    )


# -----------------------------------------------------------------------------------------------
# `jvm_artifact` targets
# -----------------------------------------------------------------------------------------------

_DEFAULT_PACKAGE_MAPPING_URL = git_url(
    "src/python/pants/jvm/dependency_inference/jvm_artifact_mappings.py"
)


class JvmArtifactGroupField(StringField):
    alias = "group"
    required = True
    value: str
    help = (
        "The 'group' part of a Maven-compatible coordinate to a third-party JAR artifact.\n\n"
        "For the JAR coordinate `com.google.guava:guava:30.1.1-jre`, the group is "
        "`com.google.guava`."
    )


class JvmArtifactArtifactField(StringField):
    alias = "artifact"
    required = True
    value: str
    help = (
        "The 'artifact' part of a Maven-compatible coordinate to a third-party JAR artifact.\n\n"
        "For the JAR coordinate `com.google.guava:guava:30.1.1-jre`, the artifact is `guava`."
    )


class JvmArtifactVersionField(StringField):
    alias = "version"
    required = True
    value: str
    help = (
        "The 'version' part of a Maven-compatible coordinate to a third-party JAR artifact.\n\n"
        "For the JAR coordinate `com.google.guava:guava:30.1.1-jre`, the version is `30.1.1-jre`."
    )


class JvmArtifactUrlField(StringField):
    alias = "url"
    required = False
    help = (
        "A URL that points to the location of this artifact.\n\n"
        "If specified, Pants will not fetch this artifact from default Maven repositories, and "
        "will instead fetch the artifact from this URL. To use default maven "
        "repositories, do not set this value.\n\n"
        "Note that `file:` URLs are not supported. Instead, use the `jar` field for local "
        "artifacts."
    )


class JvmArtifactJarSourceField(SingleSourceField):
    alias = "jar"
    expected_file_extensions = (".jar",)
    required = False
    help = (
        "A local JAR file that provides this artifact to the lockfile resolver, instead of a "
        "Maven repository.\n\n"
        "Path is relative to the BUILD file.\n\n"
        "Use the `url` field for remote artifacts."
    )

    @classmethod
    def compute_value(cls, raw_value: Optional[str], address: Address) -> Optional[str]:
        value_or_default = super().compute_value(raw_value, address)
        if value_or_default and value_or_default.startswith("file:"):
            raise InvalidFieldException(
                f"The `{cls.alias}` field does not support `file:` URLS, but the target "
                f"{address} sets the field to `{value_or_default}`.\n\n"
                "Instead, use the `jar` field to specify the relative path to the local jar file."
            )
        return value_or_default


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
        "dependency inference.\n\n"
        "This allows for specific types within packages that are otherwise inferred as "
        "belonging to `jvm_artifact` targets to be unambiguously inferred as belonging "
        "to this first-party source.\n\n"
        "If a given type is defined, at least one source file captured by this target must "
        "actually provide that symbol."
    )


class JvmArtifactCompatibleResolvesField(JvmCompatibleResolvesField):
    help = (
        "The resolves that this artifact should be included in.\n\n"
        "If not defined, will default to `[jvm].default_resolve`.\n\n"
        "Each name must be defined as a resolve in `[jvm].resolves`.\n\n"
        "When generating a lockfile for a particular resolve via the `coursier-resolve` goal, "
        "it will include all artifacts that are declared compatible with that resolve. First-party "
        "targets like `java_source` and `scala_source` then declare which resolve(s) they use "
        "via the `resolve` and `compatible_resolves` field; so, for your first-party code to use "
        "a particular `jvm_artifact` target, that artifact must be included in the resolve(s) "
        "used by that code."
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


class JvmArtifactTarget(Target):
    alias = "jvm_artifact"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        *JvmArtifactFieldSet.required_fields,
        JvmArtifactUrlField,  # TODO: should `JvmArtifactFieldSet` have an `all_fields` field?
        JvmArtifactJarSourceField,
        JvmArtifactCompatibleResolvesField,
    )
    help = (
        "A third-party JVM artifact, as identified by its Maven-compatible coordinate.\n\n"
        "That is, an artifact identified by its `group`, `artifact`, and `version` components.\n\n"
        "Each artifact is associated with one or more resolves (a logical name you give to a "
        "lockfile). For this artifact to be used by your first-party code, it must be "
        "associated with the resolve(s) used by that code. See the `compatible_resolves` field."
    )

    def validate(self) -> None:
        if self[JvmArtifactJarSourceField].value and self[JvmArtifactUrlField].value:
            raise InvalidTargetException(
                f"You cannot specify both the `url` and `jar` fields, but both were set on the "
                f"`{self.alias}` target {self.address}."
            )


# -----------------------------------------------------------------------------------------------
# JUnit test support field(s)
# -----------------------------------------------------------------------------------------------


class JunitTestSourceField(SingleSourceField, metaclass=ABCMeta):
    """A marker that indicates that a source field represents a JUnit test."""
