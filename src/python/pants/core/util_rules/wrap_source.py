# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
# This file should be moved once we figure out where everything belongs

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable, Union

from pants.core.target_types import FileSourceField
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.addresses import UnparsedAddressInputs
from pants.engine.fs import DigestSubset, PathGlobs
from pants.engine.internals.native_engine import Digest, Snapshot
from pants.engine.internals.selectors import Get
from pants.engine.rules import Rule, collect_rules, rule, rule_helper
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    GeneratedSources,
    GenerateSourcesRequest,
    MultipleSourcesField,
    SourcesField,
    SpecialCasedDependencies,
    StringSequenceField,
    Target,
    Targets,
)
from pants.engine.unions import UnionRule
from pants.util.strutil import softwrap

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WrapSource:
    rules: tuple[Union[Rule, UnionRule], ...]
    target_types: tuple[type[Target], ...]


class ActivateWrapSourceTargetFieldBase(MultipleSourcesField):
    # We solely register so that codegen can match a fieldset.
    # One unique subclass must be defined per target type.
    alias = "_sources"
    uses_source_roots = False
    expected_num_files = 0


class WrapSourceInputsField(SpecialCasedDependencies):
    alias = "inputs"
    required = True
    help = "The input targets that are to be made available by this target."


class WrapSourceOutputsField(StringSequenceField):
    alias = "outputs"
    required = False
    help = softwrap(
        "The output files that are made available in the new context by this target. If not "
        "specified, the target will capture all files with the expected extensions for this "
        "source format: see the help for the target for the specific extensions. If no extensions "
        "are specified and this value is not specified, all input files will be returned."
    )


@rule_helper
async def _wrap_source(wrapper: GenerateSourcesRequest) -> GeneratedSources:
    request = wrapper.protocol_target
    default_extensions = {i for i in (wrapper.output.expected_file_extensions or ()) if i}

    inputs = await Get(
        Targets,
        UnparsedAddressInputs,
        request.get(WrapSourceInputsField).to_unparsed_address_inputs(),
    )

    sources = await Get(
        SourceFiles,
        SourceFilesRequest(
            sources_fields=[tgt.get(SourcesField) for tgt in inputs],
            for_sources_types=(SourcesField, FileSourceField),
            enable_codegen=True,
        ),
    )

    outputs_value: Iterable[str] | None = request.get(WrapSourceOutputsField).value
    if outputs_value:
        pass
    elif default_extensions:
        outputs_value = [i for i in sources.files if any(i.endswith(j) for j in default_extensions)]
    else:
        outputs_value = sources.files

    filter_digest = await Get(
        Digest, DigestSubset(sources.snapshot.digest, PathGlobs(outputs_value))
    )

    snapshot = await Get(Snapshot, Digest, filter_digest)
    return GeneratedSources(snapshot)


def wrap_source_rule_and_target(
    source_field_type: type[SourcesField], target_name_suffix: str
) -> WrapSource:

    if source_field_type.expected_file_extensions:
        outputs_help = (
            "If `outputs` is not specified, all files with the following extensions will be "
            "matched: " + ", ".join(source_field_type.expected_file_extensions)
        )
    else:
        outputs_help = "If `outputs` is not specified, all files from `inputs` will be matched"

    class ActivateWrapSourceTargetField(ActivateWrapSourceTargetFieldBase):
        pass

    class GenerateWrapSourceSourcesRequest(GenerateSourcesRequest):
        input = ActivateWrapSourceTargetField
        output = source_field_type

    class WrapSourceTarget(Target):
        alias = f"experimental_wrap_as_{target_name_suffix}"
        core_fields = (
            *COMMON_TARGET_FIELDS,
            ActivateWrapSourceTargetField,
            WrapSourceInputsField,
            WrapSourceOutputsField,
        )
        help = softwrap(
            "Allow files and sources produced by the targets specified by `inputs` to be consumed "
            f"by rules that specifically expect a `{source_field_type.__name__}`. Note that this "
            f"rule does not modify the files in any way. {outputs_help}"
        )

    # need to use `_param_type_overrides` to stop `@rule` from inspecting the source
    @rule(_param_type_overrides={"request": GenerateWrapSourceSourcesRequest})
    async def wrap_source(request: GenerateSourcesRequest) -> GeneratedSources:
        return await _wrap_source(request)

    return WrapSource(
        rules=(
            *collect_rules(locals()),
            UnionRule(GenerateSourcesRequest, GenerateWrapSourceSourcesRequest),
        ),
        target_types=(WrapSourceTarget,),
    )
