# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import ClassVar

from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    MultipleSourcesField,
    SingleSourceField,
    Target,
    TargetFilesGenerator,
    generate_multiple_sources_field_help_message,
)


class SemgrepRuleSourceField(SingleSourceField):
    expected_file_extensions: ClassVar[tuple[str, ...]] = (".yml", ".yaml")


class SemgrepRuleGeneratingSourcesField(MultipleSourcesField):
    expected_file_extensions: ClassVar[tuple[str, ...]] = (".yml", ".yaml")
    default = (
        ".semgrep.yml",
        ".semgrep.yaml",
        ".semgrep/*.yml",
        ".semgrep/*.yaml",
    )
    help = generate_multiple_sources_field_help_message(
        "Example: `sources=['.semgrep.yml', '.semgrep.yaml', '.semgrep/*.yml', '.semgrep/*.yaml',]`"
    )


class SemgrepRuleSourceTarget(Target):
    alias = "semgrep_rule_source"
    core_fields = (*COMMON_TARGET_FIELDS, SemgrepRuleSourceField)

    help = "A single source file containing Semgrep rules"


class SemgrepRuleSourcesGeneratorTarget(TargetFilesGenerator):
    alias = "semgrep_rule_sources"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        SemgrepRuleGeneratingSourcesField,
    )
    generated_target_cls = SemgrepRuleSourceTarget
    copied_fields = COMMON_TARGET_FIELDS
    moved_fields = ()
    help = "Generate a `semgrep_rule_source` target for each file in the `sources` field."
