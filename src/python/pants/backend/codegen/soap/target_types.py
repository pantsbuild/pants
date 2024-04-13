# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.engine.rules import collect_rules, rule
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    AllTargets,
    Dependencies,
    MultipleSourcesField,
    SingleSourceField,
    Target,
    TargetFilesGenerator,
    Targets,
    generate_multiple_sources_field_help_message,
)
from pants.util.logging import LogLevel


class WsdlDependenciesField(Dependencies):
    pass


class AllWsdlTargets(Targets):
    pass


@rule(desc="Find all WSDL sources in a project", level=LogLevel.DEBUG)
def find_all_wsdl_targets(all_targets: AllTargets) -> AllWsdlTargets:
    return AllWsdlTargets([tgt for tgt in all_targets if tgt.has_field(WsdlSourceField)])


# -----------------------------------------------------------------------------------------------
# `wsdl_source` target
# -----------------------------------------------------------------------------------------------


class WsdlSourceField(SingleSourceField):
    expected_file_extensions = (".wsdl",)


class WsdlSourceTarget(Target):
    alias = "wsdl_source"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        WsdlDependenciesField,
        WsdlSourceField,
    )
    help = "A single WSDL file used to generate various languages."


# -----------------------------------------------------------------------------------------------
# `wsdl_sources` target generator
# -----------------------------------------------------------------------------------------------


class WsdlSourcesGeneratingSourcesField(MultipleSourcesField):
    default = ("*.wsdl",)
    expected_file_extensions = (".wsdl",)
    help = generate_multiple_sources_field_help_message(
        "Example: `sources=['utils.wsdl', 'models/*.wsdl', '!ignore_me.wsdl']`"
    )


class WsdlSourcesGeneratorTarget(TargetFilesGenerator):
    alias = "wsdl_sources"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        WsdlSourcesGeneratingSourcesField,
    )
    generated_target_cls = WsdlSourceTarget
    copied_fields = COMMON_TARGET_FIELDS
    moved_fields = (WsdlDependenciesField,)
    help = "Generate a `wsdl_source` target for each file in the `sources` field."


def rules():
    return collect_rules()
