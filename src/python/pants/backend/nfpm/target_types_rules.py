# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.nfpm.fields.contents import (
    NfpmContentDstField,
    NfpmContentFileSourceField,
    NfpmContentFilesField,
    NfpmContentSrcField,
)
from pants.backend.nfpm.target_types import NfpmContentFile, NfpmContentFiles
from pants.engine.rules import collect_rules, rule
from pants.engine.target import GenerateTargetsRequest, GeneratedTargets, InvalidFieldException
from pants.engine.unions import UnionMembership, UnionRule
from pants.util.logging import LogLevel
from pants.util.strutil import softwrap


class GenerateTargetsFromNfpmContentFilesRequest(GenerateTargetsRequest):
    generate_from = NfpmContentFiles


@rule(
    desc="Generate `nfmp_content_file` targets from `nfpm_content_files` target",
    level=LogLevel.DEBUG,
)
async def generate_targets_from_nfpm_content_files(
    request: GenerateTargetsFromNfpmContentFilesRequest,
    union_membership: UnionMembership,
) -> GeneratedTargets:
    generator: NfpmContentFiles = request.generator
    # This is not a dict because the same src can be copied to more than one dst.
    # Also, the field guarantees that there are no dst duplicates in this field.
    src_dst_map: tuple[tuple[str, str]] = generator[NfpmContentFilesField].value

    overrides = request.require_unparametrized_overrides()

    def generate_tgt(src: str, dst: str) -> NfpmContentFile:
        tgt_overrides = overrides.pop(dst, {})
        return NfpmContentFile(
            {
                **request.template,
                NfpmContentFileSourceField.alias: None,
                NfpmContentSrcField.alias: src,
                NfpmContentDstField.alias: dst,
                **tgt_overrides,
            },
            # We use 'dst' as 'src' is not always unique.
            # This results in an address like: path/to:nfpm_content#/dst/install/path
            request.template_address.create_generated(dst),
            union_membership,
        )

    generated_targets = [generate_tgt(src, dst) for src, dst in src_dst_map]

    if overrides:
        raise InvalidFieldException(
            softwrap(
                f"""
                Unused key in the `overrides` field for {request.template_address}:
                {sorted(overrides)}
                """
            )
        )

    return GeneratedTargets(generator, generated_targets)


def rules():
    return (
        *collect_rules(),
        UnionRule(GenerateTargetsRequest, GenerateTargetsFromNfpmContentFilesRequest),
    )
