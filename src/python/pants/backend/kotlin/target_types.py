# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
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
from pants.jvm.target_types import JvmJdkField, JvmProvidesTypesField, JvmResolveField


class KotlinSourceField(SingleSourceField):
    expected_file_extensions = (".kt",)


class KotlinGeneratorSourcesField(MultipleSourcesField):
    expected_file_extensions = (".kt",)


@dataclass(frozen=True)
class KotlinFieldSet(FieldSet):
    required_fields = (KotlinSourceField,)

    sources: KotlinSourceField


@dataclass(frozen=True)
class KotlinGeneratorFieldSet(FieldSet):
    required_fields = (KotlinGeneratorSourcesField,)

    sources: KotlinGeneratorSourcesField


# -----------------------------------------------------------------------------------------------
# `kotlin_source` and `kotlin_sources` targets
# -----------------------------------------------------------------------------------------------


class KotlinSourceTarget(Target):
    alias = "kotlin_source"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        Dependencies,
        KotlinSourceField,
        JvmResolveField,
        JvmProvidesTypesField,
        JvmJdkField,
    )
    help = "A single Kotlin source file containing application or library code."


class KotlinSourcesGeneratorSourcesField(KotlinGeneratorSourcesField):
    default = ("*.kt",)


class KotlinSourcesGeneratorTarget(TargetFilesGenerator):
    alias = "kotlin_sources"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        KotlinSourcesGeneratorSourcesField,
    )
    generated_target_cls = KotlinSourceTarget
    copied_fields = COMMON_TARGET_FIELDS
    moved_fields = (
        Dependencies,
        JvmResolveField,
        JvmJdkField,
        JvmProvidesTypesField,
    )
    help = "Generate a `kotlin_source` target for each file in the `sources` field."


def rules():
    return collect_rules()
