# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from typing import ClassVar

from pants.backend.python.target_types import PexBinary
from pants.core.target_types import ResourcesGeneratorTarget, ResourceSourceField, ResourceTarget
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
from pants.util.strutil import help_text


# Subclassing ResourceSourceField will make sure the sql is included in
# distributions as a resource.
class SqlSourceField(ResourceSourceField):
    pass


class SqlDependenciesField(Dependencies):
    pass


class SqlSourcesGeneratingSourcesField(MultipleSourcesField):
    default = ("*.sql",)
    help = generate_multiple_sources_field_help_message(
        "Example: `sources=['example.sql', 'new_*.sql', '!old_ignore.sql']`"
    )


class SqlSourceTarget(Target):
    alias = "sql_source"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        SqlSourceField,
        SqlDependenciesField,
    )
    help = help_text(
        f"""
        A single SQL source file.

        `{alias}` is treated like `{ResourceTarget.alias}` by other targets like
        `{PexBinary.alias}`.
        """
    )


class SqlSourcesOverridesField(OverridesField):
    help = generate_file_based_overrides_field_help_message(
        SqlSourceTarget.alias,
        """
        overrides={
            "query.sql": {"skip_sqlfluff": True},
            ("upload.sql", "download.sql"): {"tags": ["hive"]},
        }
        """,
    )


class SqlSourcesGeneratorTarget(TargetFilesGenerator):
    alias = "sql_sources"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        SqlSourcesGeneratingSourcesField,
        SqlSourcesOverridesField,
    )
    generated_target_cls = SqlSourceTarget
    copied_fields = COMMON_TARGET_FIELDS
    moved_fields = (SqlDependenciesField,)
    help = help_text(
        f"""
        Generate a `{SqlSourceTarget.alias}` target for each file in the
        `sources` field.

        `{alias}` are treated like `{ResourcesGeneratorTarget.alias}` by other
        targets like `{PexBinary.alias}`.
        """
    )
