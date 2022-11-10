# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import dataclasses
from abc import ABC, ABCMeta, abstractmethod
from dataclasses import dataclass
from typing import ClassVar, Iterable, Optional, Tuple, Type

from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.core.goals.generate_lockfiles import UnrecognizedResolveNamesError
from pants.core.goals.package import OutputPathField
from pants.core.goals.run import RestartableField
from pants.core.goals.test import TestExtraEnvVarsField, TestTimeoutField
from pants.engine.addresses import Address
from pants.engine.rules import collect_rules, rule
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    AsyncFieldMixin,
    Dependencies,
    FieldDefaultFactoryRequest,
    FieldDefaultFactoryResult,
    FieldSet,
    InvalidFieldException,
    InvalidTargetException,
    OptionalSingleSourceField,
    SequenceField,
    SingleSourceField,
    SpecialCasedDependencies,
    StringField,
    StringSequenceField,
    Target,
)
from pants.engine.unions import UnionRule
from pants.jvm.subsystems import JvmSubsystem
from pants.util.docutil import git_url
from pants.util.strutil import bullet_list, pluralize, softwrap

# -----------------------------------------------------------------------------------------------
# Generic resolve support fields
# -----------------------------------------------------------------------------------------------


class JvmDependenciesField(Dependencies):
    pass


class JvmResolveField(StringField, AsyncFieldMixin):
    alias = "resolve"
    required = False
    help = softwrap(
        """
        The resolve from `[jvm].resolves` to use when compiling this target.

        If not defined, will default to `[jvm].default_resolve`.
        """
        # TODO: Document expectations for dependencies once we validate that.
    )

    def normalized_value(self, jvm_subsystem: JvmSubsystem) -> str:
        """Get the value after applying the default and validating that the key is recognized."""
        resolve = self.value or jvm_subsystem.default_resolve
        if resolve not in jvm_subsystem.resolves:
            raise UnrecognizedResolveNamesError(
                [resolve],
                jvm_subsystem.resolves.keys(),
                description_of_origin=f"the field `{self.alias}` in the target {self.address}",
            )
        return resolve


class JvmJdkField(StringField):
    alias = "jdk"
    required = False
    help = softwrap(
        """
        The major version of the JDK that this target should be built with. If not defined,
        will default to `[jvm].default_source_jdk`.
        """
    )


class PrefixedJvmJdkField(JvmJdkField):
    alias = "jvm_jdk"


class PrefixedJvmResolveField(JvmResolveField):
    alias = "jvm_resolve"


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
    help = softwrap(
        """
        The 'group' part of a Maven-compatible coordinate to a third-party JAR artifact.

        For the JAR coordinate `com.google.guava:guava:30.1.1-jre`, the group is `com.google.guava`.
        """
    )


class JvmArtifactArtifactField(StringField):
    alias = "artifact"
    required = True
    value: str
    help = softwrap(
        """
        The 'artifact' part of a Maven-compatible coordinate to a third-party JAR artifact.

        For the JAR coordinate `com.google.guava:guava:30.1.1-jre`, the artifact is `guava`.
        """
    )


class JvmArtifactVersionField(StringField):
    alias = "version"
    required = True
    value: str
    help = softwrap(
        """
        The 'version' part of a Maven-compatible coordinate to a third-party JAR artifact.

        For the JAR coordinate `com.google.guava:guava:30.1.1-jre`, the version is `30.1.1-jre`.
        """
    )


class JvmArtifactUrlField(StringField):
    alias = "url"
    required = False
    help = softwrap(
        """
        A URL that points to the location of this artifact.

        If specified, Pants will not fetch this artifact from default Maven repositories, and
        will instead fetch the artifact from this URL. To use default maven
        repositories, do not set this value.

        Note that `file:` URLs are not supported. Instead, use the `jar` field for local
        artifacts.
        """
    )


class JvmArtifactJarSourceField(OptionalSingleSourceField):
    alias = "jar"
    expected_file_extensions = (".jar",)
    help = softwrap(
        """
        A local JAR file that provides this artifact to the lockfile resolver, instead of a
        Maven repository.

        Path is relative to the BUILD file.

        Use the `url` field for remote artifacts.
        """
    )

    @classmethod
    def compute_value(cls, raw_value: Optional[str], address: Address) -> Optional[str]:
        value_or_default = super().compute_value(raw_value, address)
        if value_or_default and value_or_default.startswith("file:"):
            raise InvalidFieldException(
                softwrap(
                    f"""
                    The `{cls.alias}` field does not support `file:` URLS, but the target
                    {address} sets the field to `{value_or_default}`.

                    Instead, use the `jar` field to specify the relative path to the local jar file.
                    """
                )
            )
        return value_or_default


class JvmArtifactPackagesField(StringSequenceField):
    alias = "packages"
    help = softwrap(
        f"""
        The JVM packages this artifact provides for the purposes of dependency inference.

        For example, the JVM artifact `junit:junit` might provide `["org.junit.**"]`.

        Usually you can leave this field off. If unspecified, Pants will fall back to the
        `[java-infer].third_party_import_mapping`, then to a built in mapping
        ({_DEFAULT_PACKAGE_MAPPING_URL}), and then finally it will default to
        the normalized `group` of the artifact. For example, in the absence of any other mapping
        the artifact `io.confluent:common-config` would default to providing
        `["io.confluent.**"]`.

        The package path may be made recursive to match symbols in subpackages
        by adding `.**` to the end of the package path. For example, specify `["org.junit.**"]`
        to infer a dependency on the artifact for any file importing a symbol from `org.junit` or
        its subpackages.
        """
    )


class JvmProvidesTypesField(StringSequenceField):
    alias = "experimental_provides_types"
    help = softwrap(
        """
        Signals that the specified types should be fulfilled by these source files during
        dependency inference.

        This allows for specific types within packages that are otherwise inferred as
        belonging to `jvm_artifact` targets to be unambiguously inferred as belonging
        to this first-party source.

        If a given type is defined, at least one source file captured by this target must
        actually provide that symbol.
        """
    )


class JvmArtifactExcludeDependenciesField(StringSequenceField):
    alias = "excludes"
    help = softwrap(
        """
        A list of unversioned coordinates (i.e. `group:artifact`) that should be excluded
        as dependencies when this artifact is resolved.

        This does not prevent this artifact from being included in the resolve as a dependency
        of other artifacts that depend on it, and is currently intended as a way to resolve
        version conflicts in complex resolves.

        These values are passed directly to Coursier, and if specified incorrectly will show a
        parse error from Coursier.
        """
    )


class JvmArtifactResolveField(JvmResolveField):
    help = softwrap(
        """
        The resolve from `[jvm].resolves` that this artifact should be included in.

        If not defined, will default to `[jvm].default_resolve`.

        When generating a lockfile for a particular resolve via the `coursier-resolve` goal,
        it will include all artifacts that are declared compatible with that resolve. First-party
        targets like `java_source` and `scala_source` also declare which resolve they use
        via the `resolve` field; so, for your first-party code to use
        a particular `jvm_artifact` target, that artifact must be included in the resolve
        used by that code.
        """
    )


@dataclass(frozen=True)
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
        JvmArtifactResolveField,
        JvmArtifactExcludeDependenciesField,
    )
    help = softwrap(
        """
        A third-party JVM artifact, as identified by its Maven-compatible coordinate.

        That is, an artifact identified by its `group`, `artifact`, and `version` components.

        Each artifact is associated with one or more resolves (a logical name you give to a
        lockfile). For this artifact to be used by your first-party code, it must be
        associated with the resolve(s) used by that code. See the `resolve` field.
        """
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


class JunitTestTimeoutField(TestTimeoutField):
    pass


class JunitTestExtraEnvVarsField(TestExtraEnvVarsField):
    pass


# -----------------------------------------------------------------------------------------------
# JAR support fields
# -----------------------------------------------------------------------------------------------


class JvmMainClassNameField(StringField):
    alias = "main"
    required = True
    help = softwrap(
        """
        `.`-separated name of the JVM class containing the `main()` method to be called when
        executing this JAR.
        """
    )


class JvmShadingRule(ABC):
    """Base class for defining JAR shading rules as valid aliases in BUILD files.

    Subclasses need to provide with an `alias` and a `help` message. The `alias` represents
    the name that will be used in BUILD files to instantiate the given subclass.

    Set the `help` class property with a description, which will be used in `./pants help`. For the
    best rendering, use soft wrapping (e.g. implicit string concatenation) within paragraphs, but
    hard wrapping (`\n`) to separate distinct paragraphs and/or lists.
    """

    alias: ClassVar[str]
    help: ClassVar[str]

    @abstractmethod
    def encode(self) -> str:
        pass

    @abstractmethod
    def validate(self) -> set[str]:
        pass

    @staticmethod
    def _validate_field(value: str, *, name: str, invalid_chars: str) -> set[str]:
        errors = []
        for ch in invalid_chars:
            if ch in value:
                errors.append(f"`{name}` can not contain the character `{ch}`.")
        return set(errors)

    def __repr__(self) -> str:
        fields = [f"{fld.name}={repr(getattr(self, fld.name))}" for fld in dataclasses.fields(self)]
        return f"{self.alias}({', '.join(fields)})"


@dataclass(frozen=True, repr=False)
class JvmShadingRenameRule(JvmShadingRule):
    alias = "shading_rename"
    help = "Renames all occurrences of the given `pattern` by the `replacement`."

    pattern: str
    replacement: str

    def encode(self) -> str:
        return f"rule {self.pattern} {self.replacement}"

    def validate(self) -> set[str]:
        errors: list[str] = []
        errors.extend(
            JvmShadingRule._validate_field(self.pattern, name="pattern", invalid_chars="/")
        )
        errors.extend(
            JvmShadingRule._validate_field(self.replacement, name="replacement", invalid_chars="/")
        )
        return set(errors)


@dataclass(frozen=True, repr=False)
class JvmShadingRelocateRule(JvmShadingRule):
    alias = "shading_relocate"
    help = softwrap(
        """
        Relocates the classes under the given `package` into the new package name.
        The default target package is `__shaded_by_pants__` if none provided in
        the `into` parameter.
        """
    )

    package: str
    into: str | None = None

    def encode(self) -> str:
        if not self.into:
            target_suffix = "__shaded_by_pants__"
        else:
            target_suffix = self.into
        return f"rule {self.package}.** {target_suffix}.@1"

    def validate(self) -> set[str]:
        errors: list[str] = []
        errors.extend(
            JvmShadingRule._validate_field(self.package, name="package", invalid_chars="/*")
        )
        if self.into:
            errors.extend(
                JvmShadingRule._validate_field(self.into, name="into", invalid_chars="/*")
            )
        return set(errors)


@dataclass(frozen=True, repr=False)
class JvmShadingZapRule(JvmShadingRule):
    alias = "shading_zap"
    help = "Removes from the final artifact the occurrences of the `pattern`."

    pattern: str

    def encode(self) -> str:
        return f"zap {self.pattern}"

    def validate(self) -> set[str]:
        return JvmShadingRule._validate_field(self.pattern, name="pattern", invalid_chars="/")


@dataclass(frozen=True, repr=False)
class JvmShadingKeepRule(JvmShadingRule):
    alias = "shading_keep"
    help = softwrap(
        """
        Keeps in the final artifact the occurrences of the `pattern`
        (and removes anything else).
        """
    )

    pattern: str

    def encode(self) -> str:
        return f"keep {self.pattern}"

    def validate(self) -> set[str]:
        return JvmShadingRule._validate_field(self.pattern, name="pattern", invalid_chars="/")


JVM_SHADING_RULE_TYPES: list[Type[JvmShadingRule]] = [
    JvmShadingRelocateRule,
    JvmShadingRenameRule,
    JvmShadingZapRule,
    JvmShadingKeepRule,
]


def _shading_rules_field_help(intro: str) -> str:
    return softwrap(
        f"""
        {intro}

        There are {pluralize(len(JVM_SHADING_RULE_TYPES), "possible shading rule")} available,
        which are as follows:
        {bullet_list([f'`{rule.alias}`: {rule.help}' for rule in JVM_SHADING_RULE_TYPES])}

        When defining shading rules, just add them in this field using the previously listed rule
        alias and passing along the required parameters.
        """
    )


def _shading_validate_rules(shading_rules: Iterable[JvmShadingRule]) -> set[str]:
    validation_errors = []
    for shading_rule in shading_rules:
        found_errors = shading_rule.validate()
        if found_errors:
            validation_errors.append(
                "\n".join(
                    [
                        f"In rule `{shading_rule.alias}`:",
                        bullet_list(found_errors),
                        "",
                    ]
                )
            )
    return set(validation_errors)


class JvmShadingRulesField(SequenceField[JvmShadingRule], metaclass=ABCMeta):
    alias = "shading_rules"
    required = False
    expected_element_type = JvmShadingRule
    expected_type_description = "an iterable of ShadingRule"

    @classmethod
    def compute_value(
        cls, raw_value: Optional[Iterable[JvmShadingRule]], address: Address
    ) -> Optional[Tuple[JvmShadingRule, ...]]:
        computed_value = super().compute_value(raw_value, address)

        if computed_value:
            validation_errors = _shading_validate_rules(computed_value)
            if validation_errors:
                raise InvalidFieldException(
                    "\n".join(
                        [
                            f"Invalid shading rules assigned to `{cls.alias}` field in target {address}:\n",
                            *validation_errors,
                        ]
                    )
                )

        return computed_value


# -----------------------------------------------------------------------------------------------
# `deploy_jar` target
# -----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class DeployJarDuplicateRule:
    alias: ClassVar[str] = "duplicate_rule"
    valid_actions: ClassVar[tuple[str, ...]] = ("skip", "replace", "concat", "concat_text", "throw")

    pattern: str
    action: str

    def validate(self) -> str | None:
        if self.action not in DeployJarDuplicateRule.valid_actions:
            return softwrap(
                f"""
                Value '{self.action}' for `action` associated with pattern
                '{self.pattern}' is not valid.

                It must be one of {list(DeployJarDuplicateRule.valid_actions)}.
                """
            )
        return None

    def __repr__(self) -> str:
        return f"{self.alias}(pattern='{self.pattern}', action='{self.action}')"


class DeployJarDuplicatePolicyField(SequenceField[DeployJarDuplicateRule]):
    alias = "duplicate_policy"
    help = softwrap(
        f"""
        A list of the rules to apply when duplicate file entries are found in the final
        assembled JAR file.

        When defining a duplicate policy, just add `duplicate_rule` directives to this
        field as follows:

        Example:

        ```
        duplicate_policy=[
            duplicate_rule(pattern="^META-INF/services", action="concat_text"),
            duplicate_rule(pattern="^reference\\.conf", action="concat_text"),
            duplicate_rule(pattern="^org/apache/commons", action="throw"),
        ]
        ```

        Where:

        * The `pattern` field is treated as a regular expression
        * The `action` field must be one of {list(DeployJarDuplicateRule.valid_actions)}.

        Note that the order in which the rules are listed is relevant.
        """
    )
    required = False

    expected_element_type = DeployJarDuplicateRule
    expected_type_description = "a list of JAR duplicate rules"

    default = (
        DeployJarDuplicateRule(pattern="^META-INF/services/", action="concat_text"),
        DeployJarDuplicateRule(pattern="^META-INF/LICENSE", action="skip"),
    )

    @classmethod
    def compute_value(
        cls, raw_value: Optional[Iterable[DeployJarDuplicateRule]], address: Address
    ) -> Optional[Tuple[DeployJarDuplicateRule, ...]]:
        value = super().compute_value(raw_value, address)
        if value:
            errors = []
            for duplicate_rule in value:
                err = duplicate_rule.validate()
                if err:
                    errors.append(err)

            if errors:
                raise InvalidFieldException(
                    softwrap(
                        f"""
                        Invalid value for `{DeployJarDuplicatePolicyField.alias}` field.
                        Found following errors:

                        {bullet_list(errors)}
                        """
                    )
                )
        return value

    def value_or_default(self) -> tuple[DeployJarDuplicateRule, ...]:
        if self.value is not None:
            return self.value
        return self.default


class DeployJarShadingRulesField(JvmShadingRulesField):
    help = _shading_rules_field_help("Shading rules to be applied to the final JAR artifact.")


class DeployJarTarget(Target):
    alias = "deploy_jar"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        RestartableField,
        OutputPathField,
        JvmDependenciesField,
        JvmMainClassNameField,
        JvmJdkField,
        JvmResolveField,
        DeployJarDuplicatePolicyField,
        DeployJarShadingRulesField,
    )
    help = softwrap(
        """
        A `jar` file with first and third-party code bundled for deploys.

        The JAR will contain class files for both first-party code and
        third-party dependencies, all in a common directory structure.
        """
    )


# -----------------------------------------------------------------------------------------------
# `jvm_war` targets
# -----------------------------------------------------------------------------------------------


class JvmWarDependenciesField(Dependencies):
    pass


class JvmWarDescriptorAddressField(SingleSourceField):
    alias = "descriptor"
    default = "web.xml"
    help = "Path to a file containing the descriptor (i.e., web.xml) for this WAR file. Defaults to `web.xml`."


class JvmWarContentField(SpecialCasedDependencies):
    alias = "content"
    help = softwrap(
        """
        A list of addresses to `resources` and `files` targets with content to place in the
        document root of this WAR file.
        """
    )


class JvmWarShadingRulesField(JvmShadingRulesField):
    help = _shading_rules_field_help(
        "Shading rules to be applied to the individual JAR artifacts embedded in the `WEB-INF/lib` folder."
    )


class JvmWarTarget(Target):
    alias = "jvm_war"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        JvmResolveField,
        JvmWarContentField,
        JvmWarDependenciesField,
        JvmWarDescriptorAddressField,
        JvmWarShadingRulesField,
        OutputPathField,
    )
    help = softwrap(
        """
        A JSR 154 "web application archive" (or "war") with first-party and third-party code bundled for
        deploys in Java Servlet containers.
        """
    )


# -----------------------------------------------------------------------------------------------
# Dynamic Field defaults
# -----------------------------------------------------------------------------------------------#


class JvmResolveFieldDefaultFactoryRequest(FieldDefaultFactoryRequest):
    field_type = JvmResolveField


@rule
def jvm_resolve_field_default_factory(
    request: JvmResolveFieldDefaultFactoryRequest,
    jvm: JvmSubsystem,
) -> FieldDefaultFactoryResult:
    return FieldDefaultFactoryResult(lambda f: f.normalized_value(jvm))


def rules():
    return [
        *collect_rules(),
        UnionRule(FieldDefaultFactoryRequest, JvmResolveFieldDefaultFactoryRequest),
    ]


def build_file_aliases():
    return BuildFileAliases(
        objects={
            DeployJarDuplicateRule.alias: DeployJarDuplicateRule,
            **{rule.alias: rule for rule in JVM_SHADING_RULE_TYPES},
        }
    )
