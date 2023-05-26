# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from pants.backend.kotlin.compile import kotlinc, kotlinc_plugins
from pants.backend.kotlin.dependency_inference.rules import rules as dep_inf_rules
from pants.backend.kotlin.goals import check, tailor
from pants.backend.kotlin.target_types import (
    KotlinJmhBenchmarkTarget,
    KotlinJmhBenckmarksGeneratorTarget,
    KotlincPluginTarget,
    KotlinJunitTestsGeneratorTarget,
    KotlinJunitTestTarget,
    KotlinSourceField,
    KotlinSourcesGeneratorTarget,
    KotlinSourceTarget,
)
from pants.backend.kotlin.target_types import rules as target_types_rules
from pants.backend.kotlin.test.junit import rules as kotlin_junit_rules
from pants.core.util_rules import source_files, system_binaries
from pants.core.util_rules.wrap_source import wrap_source_rule_and_target
from pants.jvm import jvm_common

wrap_kotlin = wrap_source_rule_and_target(KotlinSourceField, "kotlin_sources")


def target_types():
    return [
        KotlinSourceTarget,
        KotlinSourcesGeneratorTarget,
        KotlincPluginTarget,
        KotlinJmhBenchmarkTarget,
        KotlinJmhBenckmarksGeneratorTarget,
        KotlinJunitTestTarget,
        KotlinJunitTestsGeneratorTarget,
        *jvm_common.target_types(),
        *wrap_kotlin.target_types,
    ]


def rules():
    return [
        *kotlinc.rules(),
        *kotlinc_plugins.rules(),
        *check.rules(),
        *tailor.rules(),
        *dep_inf_rules(),
        *target_types_rules(),
        *system_binaries.rules(),
        *source_files.rules(),
        *kotlin_junit_rules(),
        *jvm_common.rules(),
        *wrap_kotlin.rules,
    ]


def build_file_aliases():
    return jvm_common.build_file_aliases()
