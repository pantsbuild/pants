# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass

from pants.engine.rules import collect_rules
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    FieldSet,
    MultipleSourcesField,
    SingleSourceField,
    Target,
    TargetFilesGenerator,
    generate_multiple_sources_field_help_message,
)
from pants.jvm import target_types as jvm_target_types
from pants.jvm.target_types import (
    JmhBenchmarkExtraEnvVarsField,
    JmhBenchmarkSourceField,
    JmhBenchmarkTimeoutField,
    JunitTestExtraEnvVarsField,
    JunitTestSourceField,
    JunitTestTimeoutField,
    JvmDependenciesField,
    JvmJdkField,
    JvmMainClassNameField,
    JvmProvidesTypesField,
    JvmResolveField,
    JvmRunnableSourceFieldSet,
)


class JavaSourceField(SingleSourceField):
    expected_file_extensions = (".java",)


class JavaGeneratorSourcesField(MultipleSourcesField):
    expected_file_extensions = (".java",)


@dataclass(frozen=True)
class JavaFieldSet(JvmRunnableSourceFieldSet):
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
        JunitTestTimeoutField,
        JunitTestExtraEnvVarsField,
        JvmDependenciesField,
        JvmResolveField,
        JvmProvidesTypesField,
        JvmJdkField,
    )
    help = "A single Java test, run with JUnit."


class JavaTestsGeneratorSourcesField(JavaGeneratorSourcesField):
    default = ("*Test.java",)
    help = generate_multiple_sources_field_help_message(
        "Example: `sources=['*Test.java', '!TestIgnore.java']`"
    )


class JunitTestsGeneratorTarget(TargetFilesGenerator):
    alias = "junit_tests"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        JavaTestsGeneratorSourcesField,
    )
    generated_target_cls = JunitTestTarget
    copied_fields = COMMON_TARGET_FIELDS
    moved_fields = (
        JunitTestTimeoutField,
        JunitTestExtraEnvVarsField,
        JvmDependenciesField,
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
        JvmDependenciesField,
        JavaSourceField,
        JvmResolveField,
        JvmMainClassNameField,
        JvmProvidesTypesField,
        JvmJdkField,
    )
    help = "A single Java source file containing application or library code."


class JavaSourcesGeneratorSourcesField(JavaGeneratorSourcesField):
    default = ("*.java",) + tuple(f"!{pat}" for pat in JavaTestsGeneratorSourcesField.default)
    help = generate_multiple_sources_field_help_message(
        "Example: `sources=['Example.java', 'New*.java', '!OldExample.java']`"
    )


class JavaSourcesGeneratorTarget(TargetFilesGenerator):
    alias = "java_sources"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        JavaSourcesGeneratorSourcesField,
    )
    generated_target_cls = JavaSourceTarget
    copied_fields = COMMON_TARGET_FIELDS
    moved_fields = (
        JvmDependenciesField,
        JvmResolveField,
        JvmJdkField,
        JvmMainClassNameField,
        JvmProvidesTypesField,
    )
    help = "Generate a `java_source` target for each file in the `sources` field."

# -----------------------------------------------------------------------------------------------
# `jmh_test` and `jmh_tests` targets
# -----------------------------------------------------------------------------------------------

class JavaJmhBenchmarkSourceField(JavaSourceField, JmhBenchmarkSourceField):
    """A JMH benchmark file written in Java."""


class JmhBenchmarkTarget(Target):
    alias = "jmh_benchmark"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        JavaJmhBenchmarkSourceField,
        JmhBenchmarkTimeoutField,
        JmhBenchmarkExtraEnvVarsField,
        JvmDependenciesField,
        JvmResolveField,
        JvmProvidesTypesField,
        JvmJdkField,
    )
    help = "A single Java benchmark, run with JMH."


class JavaJmhBenckmarksGeneratorSourcesField(JavaGeneratorSourcesField):
    default = ("*Benchmark.java",)
    help = generate_multiple_sources_field_help_message(
        "Example: `sources=['*Benchmark.java', '!BenchmarkIgnore.java']`"
    )


class JmhBenckmarksGeneratorTarget(TargetFilesGenerator):
    alias = "jmh_benchmarks"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        JavaJmhBenckmarksGeneratorSourcesField,
    )
    generated_target_cls = JunitTestTarget
    copied_fields = COMMON_TARGET_FIELDS
    moved_fields = (
        JmhBenchmarkTimeoutField,
        JmhBenchmarkExtraEnvVarsField,
        JvmDependenciesField,
        JvmJdkField,
        JvmProvidesTypesField,
        JvmResolveField,
    )
    help = "Generate a `junit_test` target for each file in the `sources` field."

def rules():
    return [
        *collect_rules(),
        *jvm_target_types.rules(),
        *JavaFieldSet.jvm_rules(),
    ]
