# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass

from pants.engine.rules import collect_rules
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    Dependencies,
    FieldSet,
    MultipleSourcesField,
    SingleSourceField,
    Target,
    TargetFilesGenerator,
)
from pants.jvm.target_types import (
    JunitTestSourceField,
    JvmJdkField,
    JvmProvidesTypesField,
    JvmResolveField,
)


class JavaSourceField(SingleSourceField):
    expected_file_extensions = (".java",)


class JavaGeneratorSourcesField(MultipleSourcesField):
    expected_file_extensions = (".java",)


@dataclass(frozen=True)
class JavaFieldSet(FieldSet):
    required_fields = (JavaSourceField,)

    sources: JavaSourceField


@dataclass(frozen=True)
class JavaGeneratorFieldSet(FieldSet):
    required_fields = (JavaGeneratorSourcesField,)

    sources: JavaGeneratorSourcesField


# -----------------------------------------------------------------------------------------------
# `junit_test` and `junit_tests` targets
# -----------------------------------------------------------------------------------------------


class JavaJunitTestSourceField(JavaSourceField, JunitTestSourceField):
    """A JUnit test file written in Java."""


class JunitTestTarget(Target):
    alias = "junit_test"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        JavaJunitTestSourceField,
        Dependencies,
        JvmResolveField,
        JvmProvidesTypesField,
        JvmJdkField,
    )
    help = "A single Java test, run with JUnit."


class JavaTestsGeneratorSourcesField(JavaGeneratorSourcesField):
    default = ("*Test.java",)


class JunitTestsGeneratorTarget(TargetFilesGenerator):
    alias = "junit_tests"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        JavaTestsGeneratorSourcesField,
    )
    generated_target_cls = JunitTestTarget
    copied_fields = COMMON_TARGET_FIELDS
    moved_fields = (
        Dependencies,
        JvmJdkField,
        JvmProvidesTypesField,
        JvmResolveField,
    )
    help = "Generate a `junit_test` target for each file in the `sources` field."


# -----------------------------------------------------------------------------------------------
# `java_source` and `java_sources` targets
# -----------------------------------------------------------------------------------------------


class JavaSourceTarget(Target):
    alias = "java_source"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        Dependencies,
        JavaSourceField,
        JvmResolveField,
        JvmProvidesTypesField,
        JvmJdkField,
    )
    help = "A single Java source file containing application or library code."


class JavaSourcesGeneratorSourcesField(JavaGeneratorSourcesField):
    default = ("*.java",) + tuple(f"!{pat}" for pat in JavaTestsGeneratorSourcesField.default)


class JavaSourcesGeneratorTarget(TargetFilesGenerator):
    alias = "java_sources"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        JavaSourcesGeneratorSourcesField,
    )
    generated_target_cls = JavaSourceTarget
    copied_fields = COMMON_TARGET_FIELDS
    moved_fields = (
        Dependencies,
        JvmResolveField,
        JvmJdkField,
        JvmProvidesTypesField,
    )
    help = "Generate a `java_source` target for each file in the `sources` field."


def rules():
    return collect_rules()
