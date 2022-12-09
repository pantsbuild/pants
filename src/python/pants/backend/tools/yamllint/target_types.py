# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from pants.engine.rules import collect_rules
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    MultipleSourcesField,
    SingleSourceField,
    Target,
    TargetFilesGenerator,
    generate_multiple_sources_field_help_message,
)


class YamlSourceField(SingleSourceField):
    expected_file_extensions = (".yaml",)
    uses_source_roots = False


class YamlSourcesGeneratingSourcesField(MultipleSourcesField):
    uses_source_roots = False
    default = ("*.yaml",)
    help = generate_multiple_sources_field_help_message(
        "Example: `sources=['example.yaml', 'examples_*.yaml', '!ignore_me.yaml']`"
    )


class YamlSourceTarget(Target):
    alias = "yaml_source"
    core_fields = (*COMMON_TARGET_FIELDS, YamlSourceField)
    help = "A single YAML file"


class YamlSourcesGeneratorTarget(TargetFilesGenerator):
    alias = "yaml_sources"
    core_fields = (*COMMON_TARGET_FIELDS, YamlSourcesGeneratingSourcesField)
    generated_target_cls = YamlSourceTarget
    copied_fields = COMMON_TARGET_FIELDS
    moved_fields = ()
    help = "Generate a `yaml_source` target for each file in the `sources` field."
