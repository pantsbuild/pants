# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.engine.rules import collect_rules, rule
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    Dependencies,
    MultipleSourcesField,
    OverridesField,
    SingleSourceField,
    Target,
    TargetFilesGenerator,
    TargetFilesGeneratorSettings,
    TargetFilesGeneratorSettingsRequest,
    generate_file_based_overrides_field_help_message,
)
from pants.engine.unions import UnionRule

# -----------------------------------------------------------------------------------------------
# `sphinx_source` target
# -----------------------------------------------------------------------------------------------


class SphinxSourceField(SingleSourceField):
    # TODO: support markdown
    expected_file_extensions = (".rst",)


class SphinxSourceTarget(Target):
    alias = "sphinx_source"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        Dependencies,
        SphinxSourceField,
    )
    help = "A single Sphinx file used to generate docs."


# -----------------------------------------------------------------------------------------------
# `sphinx_sources` target generator
# -----------------------------------------------------------------------------------------------


class GeneratorSettingsRequest(TargetFilesGeneratorSettingsRequest):
    pass


@rule
def generator_settings(_: GeneratorSettingsRequest) -> TargetFilesGeneratorSettings:
    return TargetFilesGeneratorSettings(
        # TODO: add dep inference and disable if set.
        add_dependencies_on_all_siblings=True
    )


class SphinxSourcesGeneratingSourcesField(MultipleSourcesField):
    # TODO: support markdown
    default = ("*.rst",)
    expected_file_extensions = (".rst",)


class SphinxSourcesOverridesField(OverridesField):
    help = generate_file_based_overrides_field_help_message(
        SphinxSourceTarget.alias,
        # TODO: make this example helpful
        (
            "overrides={\n"
            '  "foo.rst": {"grpc": True},\n'
            '  "bar.rst": {"description": "our main guide"},\n'
            '  ("foo.rst", "bar.rst"): {"tags": ["overridden"]},\n'
            "}"
        ),
    )


class SphinxSourcesGeneratorTarget(TargetFilesGenerator):
    alias = "sphinx_sources"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        SphinxSourcesGeneratingSourcesField,
        SphinxSourcesOverridesField,
    )
    generated_target_cls = SphinxSourceTarget
    copied_fields = COMMON_TARGET_FIELDS
    moved_fields = (Dependencies,)
    settings_request_cls = GeneratorSettingsRequest
    help = "Generate a `sphinx_source` target for each file in the `sources` field."


def rules():
    return [
        *collect_rules(),
        UnionRule(TargetFilesGeneratorSettingsRequest, GeneratorSettingsRequest),
    ]
