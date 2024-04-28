from typing import ClassVar

from pants.core.target_types import FileSourceField, ResourceSourceField
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    Dependencies,
    MultipleSourcesField,
    OverridesField,
    SingleSourceField,
    StringField,
    Target,
    TargetFilesGenerator,
    TargetFilesGeneratorSettingsRequest,
    generate_file_based_overrides_field_help_message,
    generate_multiple_sources_field_help_message,
)
from pants.util.strutil import help_text


# subclassing ResourceSourceField will tell pex to treat sql_source as a resource
class SqlSourceField(ResourceSourceField):
    expected_file_extensions: ClassVar[tuple[str, ...]] = (".sql",)


class SqlDependenciesField(Dependencies):
    pass


class SqlSourcesGeneratingSourcesField(MultipleSourcesField):
    expected_file_extensions: ClassVar[tuple[str, ...]] = (".sql",)
    default = ("*.sql",)
    help = generate_multiple_sources_field_help_message(
        "Example: `sources=['example.sql', 'new_*.sql', '!old_ignore.sql']`"
    )


class SqlDialectField(StringField):
    alias = "dialect"
    help = "SQL dialect."


class SqlSourceTarget(Target):
    alias = "sql_source"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        SqlSourceField,
        SqlDependenciesField,
        SqlDialectField,
    )
    help = "A single SQL source file."


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
    moved_fields = (
        SqlDependenciesField,
        SqlDialectField,
    )
    help = help_text(
        """
        Generate a `sql_source` target for each file in the `sources` field.
        """
    )
