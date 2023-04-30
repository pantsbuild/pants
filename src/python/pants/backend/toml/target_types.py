# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import ClassVar

from pants.core.target_types import FileSourceField
from pants.engine.rules import collect_rules
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    Dependencies,
    MultipleSourcesField,
    OverridesField,
    Target,
    TargetFilesGenerator,
    generate_file_based_overrides_field_help_message,
    generate_multiple_sources_field_help_message,
)


class TomlDependenciesField(Dependencies):
    pass


class TomlSourceField(FileSourceField):
    expected_file_extensions: ClassVar[tuple[str, ...]] = (".toml",)


# -----------------------------------------------------------------------------------------------
# `shell_source` and `shell_sources` targets
# -----------------------------------------------------------------------------------------------


class TomlSourceTarget(Target):
    alias = "toml_source"
    core_fields = (*COMMON_TARGET_FIELDS, TomlDependenciesField, TomlSourceField)
    help = "A single TOML file"


class TomlSourcesGeneratingSourcesField(MultipleSourcesField):
    default = ("*.toml",)
    uses_source_roots = False
    expected_file_extensions: ClassVar[tuple[str, ...]] = (".toml",)
    help = generate_multiple_sources_field_help_message(
        "Example: `sources=['pyproject.toml', 'config.toml']`"
    )


class TomlSourcesOverridesField(OverridesField):
    help = generate_file_based_overrides_field_help_message(
        TomlSourceTarget.alias,
        """
        overrides={
            "foo.toml": {"skip_taplo": True},
            ("foo.toml", "pyproject.toml"): {"tags": ["linter_disabled"]},
        }
        """,
    )


class TomlSourcesGeneratorTarget(TargetFilesGenerator):
    alias = "toml_sources"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        TomlSourcesGeneratingSourcesField,
        TomlSourcesOverridesField,
    )
    generated_target_cls = TomlSourceTarget
    copied_fields = COMMON_TARGET_FIELDS
    moved_fields = (TomlDependenciesField,)
    help = "Generate a `toml_source` target for each file in the `sources` field."


def rules():
    return [*collect_rules()]
