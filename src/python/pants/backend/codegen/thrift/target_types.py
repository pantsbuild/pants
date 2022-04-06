# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.codegen.thrift.subsystem import ThriftSubsystem
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
    TargetFilesGeneratorSettings,
    TargetFilesGeneratorSettingsRequest,
    Targets,
    generate_file_based_overrides_field_help_message,
)
from pants.engine.unions import UnionRule
from pants.util.docutil import doc_url
from pants.util.logging import LogLevel
from pants.util.strutil import softwrap


# NB: We subclass Dependencies so that specific backends can add dependency injection rules to
# `thrift_source` targets.
class ThriftDependenciesField(Dependencies):
    pass


class AllThriftTargets(Targets):
    pass


@rule(desc="Find all Thrift targets in project", level=LogLevel.DEBUG)
def find_all_thrift_targets(targets: AllTargets) -> AllThriftTargets:
    return AllThriftTargets(tgt for tgt in targets if tgt.has_field(ThriftSourceField))


class GeneratorSettingsRequest(TargetFilesGeneratorSettingsRequest):
    pass


@rule
def generator_settings(
    _: GeneratorSettingsRequest,
    thrift: ThriftSubsystem,
) -> TargetFilesGeneratorSettings:
    return TargetFilesGeneratorSettings(
        add_dependencies_on_all_siblings=not thrift.dependency_inference
    )


# -----------------------------------------------------------------------------------------------
# `thrift_source` target
# -----------------------------------------------------------------------------------------------


class ThriftSourceField(SingleSourceField):
    expected_file_extensions = (".thrift",)


class ThriftSourceTarget(Target):
    alias = "thrift_source"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        ThriftDependenciesField,
        ThriftSourceField,
    )
    help = softwrap(
        f"""
        A single Thrift file used to generate various languages.

        See {doc_url('thrift')}.
        """
    )


# -----------------------------------------------------------------------------------------------
# `thrift_sources` target generator
# -----------------------------------------------------------------------------------------------


class ThriftSourcesGeneratingSourcesField(MultipleSourcesField):
    default = ("*.thrift",)
    expected_file_extensions = (".thrift",)


class ThriftSourcesOverridesField(OverridesField):
    help = generate_file_based_overrides_field_help_message(
        ThriftSourceTarget.alias,
        (
            "overrides={\n"
            '  "bar.thrift": {"description": "our user model"]},\n'
            '  ("foo.thrift", "bar.thrift"): {"tags": ["overridden"]},\n'
            "}"
        ),
    )


class ThriftSourcesGeneratorTarget(TargetFilesGenerator):
    alias = "thrift_sources"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        ThriftSourcesGeneratingSourcesField,
        ThriftSourcesOverridesField,
    )
    generated_target_cls = ThriftSourceTarget
    copied_fields = (*COMMON_TARGET_FIELDS,)
    moved_fields = (ThriftDependenciesField,)
    settings_request_cls = GeneratorSettingsRequest
    help = "Generate a `thrift_source` target for each file in the `sources` field."


def rules():
    return [
        *collect_rules(),
        UnionRule(TargetFilesGeneratorSettingsRequest, GeneratorSettingsRequest),
    ]
