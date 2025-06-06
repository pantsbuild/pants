# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.engine.rules import collect_rules, rule
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    AllTargets,
    Dependencies,
    MultipleSourcesField,
    OverridesField,
    SingleSourceField,
    Target,
    TargetFilesGenerator,
    Targets,
    generate_file_based_overrides_field_help_message,
    generate_multiple_sources_field_help_message,
)
from pants.util.docutil import doc_url
from pants.util.logging import LogLevel
from pants.util.strutil import help_text


class AvroDependenciesField(Dependencies):
    pass


class AllAvroTargets(Targets):
    pass


@rule(desc="Find all Avro targets in project", level=LogLevel.DEBUG)
async def find_all_avro_targets(targets: AllTargets) -> AllAvroTargets:
    return AllAvroTargets(tgt for tgt in targets if tgt.has_field(AvroSourceField))


# -----------------------------------------------------------------------------------------------
# `avro_source` target
# -----------------------------------------------------------------------------------------------


class AvroSourceField(SingleSourceField):
    expected_file_extensions = (".avsc", ".avpr", ".avdl")


class AvroSourceTarget(Target):
    alias = "avro_source"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        AvroDependenciesField,
        AvroSourceField,
    )
    help = help_text(
        f"""
        A single Avro file used to generate various languages.

        See {doc_url("avro")}.
        """
    )


# -----------------------------------------------------------------------------------------------
# `avro_sources` target generator
# -----------------------------------------------------------------------------------------------


class AvroSourcesGeneratingSourcesField(MultipleSourcesField):
    default = ("*.avsc", "*.avpr", "*.avdl")
    expected_file_extensions = (".avsc", ".avpr", ".avdl")
    help = generate_multiple_sources_field_help_message(
        "Example: `sources=['example.avsc', 'new_*.avpr', '!old_ignore.avdl']`"
    )


class AvroSourcesOverridesField(OverridesField):
    help = generate_file_based_overrides_field_help_message(
        AvroSourceTarget.alias,
        """
        overrides={
            "bar.proto": {"description": "our user model"]},
            ("foo.proto", "bar.proto"): {"tags": ["overridden"]},
        }
        """,
    )


class AvroSourcesGeneratorTarget(TargetFilesGenerator):
    alias = "avro_sources"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        AvroSourcesGeneratingSourcesField,
        AvroSourcesOverridesField,
    )
    generated_target_cls = AvroSourceTarget
    copied_fields = COMMON_TARGET_FIELDS
    moved_fields = (AvroDependenciesField,)
    help = "Generate a `avro_source` target for each file in the `sources` field."


def rules():
    return collect_rules()
