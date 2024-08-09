# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.backend.nfpm.fields.contents import (
    NfpmContentDirDstField,
    NfpmContentDirsField,
    NfpmContentDstField,
    NfpmContentFilesField,
    NfpmContentFileSourceField,
    NfpmContentSrcField,
    NfpmContentSymlinkDstField,
    NfpmContentSymlinksField,
    NfpmContentSymlinkSrcField,
)
from pants.backend.nfpm.target_types import (
    NfpmContentDir,
    NfpmContentDirs,
    NfpmContentFile,
    NfpmContentFiles,
    NfpmContentSymlink,
    NfpmContentSymlinks,
)
from pants.engine.rules import collect_rules, rule
from pants.engine.target import GeneratedTargets, GenerateTargetsRequest, InvalidFieldException
from pants.engine.unions import UnionMembership, UnionRule
from pants.util.logging import LogLevel
from pants.util.strutil import softwrap


class GenerateTargetsFromNfpmContentFilesRequest(GenerateTargetsRequest):
    generate_from = NfpmContentFiles


@rule(
    desc="Generate `nfpm_content_file` targets from `nfpm_content_files` target",
    level=LogLevel.DEBUG,
)
async def generate_targets_from_nfpm_content_files(
    request: GenerateTargetsFromNfpmContentFilesRequest,
    union_membership: UnionMembership,
) -> GeneratedTargets:
    generator: NfpmContentFiles = request.generator
    # This is not a dict because the same src can be copied to more than one dst.
    # Also, the field guarantees that there are no dst duplicates in this field.
    src_dst_map: tuple[tuple[str, str], ...] = generator[NfpmContentFilesField].value or ()

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

    generated_targets: list[NfpmContentFile] = [generate_tgt(src, dst) for src, dst in src_dst_map]

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


class GenerateTargetsFromNfpmContentSymlinksRequest(GenerateTargetsRequest):
    generate_from = NfpmContentSymlinks


@rule(
    desc="Generate `nfpm_content_symlink` targets from `nfpm_content_symlinks` target",
    level=LogLevel.DEBUG,
)
async def generate_targets_from_nfpm_content_symlinks(
    request: GenerateTargetsFromNfpmContentSymlinksRequest,
    union_membership: UnionMembership,
) -> GeneratedTargets:
    generator: NfpmContentSymlinks = request.generator
    # This is not a dict because the same src can be linked to more than one dst.
    # Also, the field guarantees that there are no dst duplicates in this field.
    src_dst_map: tuple[tuple[str, str], ...] = generator[NfpmContentSymlinksField].value or ()

    overrides = request.require_unparametrized_overrides()

    def generate_tgt(src: str, dst: str) -> NfpmContentSymlink:
        tgt_overrides = overrides.pop(dst, {})
        return NfpmContentSymlink(
            {
                **request.template,
                NfpmContentSymlinkSrcField.alias: src,
                NfpmContentSymlinkDstField.alias: dst,
                **tgt_overrides,
            },
            # We use 'dst' as 'src' is not always unique.
            # This results in an address like: path/to:nfpm_content#/dst/install/path
            request.template_address.create_generated(dst),
            union_membership,
        )

    generated_targets: list[NfpmContentSymlink] = [
        generate_tgt(src, dst) for src, dst in src_dst_map
    ]

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


class GenerateTargetsFromNfpmContentDirsRequest(GenerateTargetsRequest):
    generate_from = NfpmContentDirs


@rule(
    desc="Generate `nfpm_content_dir` targets from `nfpm_content_dirs` target",
    level=LogLevel.DEBUG,
)
async def generate_targets_from_nfpm_content_dirs(
    request: GenerateTargetsFromNfpmContentDirsRequest,
    union_membership: UnionMembership,
) -> GeneratedTargets:
    generator: NfpmContentDirs = request.generator
    # This is not a dict because the same src can be linked to more than one dst.
    # Also, the field guarantees that there are no dst duplicates in this field.
    dirs: tuple[str, ...] = generator[NfpmContentDirsField].value or ()

    overrides = request.require_unparametrized_overrides()

    def generate_tgt(dst: str) -> NfpmContentDir:
        tgt_overrides = overrides.pop(dst, {})
        return NfpmContentDir(
            {
                **request.template,
                NfpmContentDirDstField.alias: dst,
                **tgt_overrides,
            },
            # We use 'dst' as 'src' is not always unique.
            # This results in an address like: path/to:nfpm_content#/dst/install/path
            request.template_address.create_generated(dst),
            union_membership,
        )

    generated_targets: list[NfpmContentDir] = [generate_tgt(dst) for dst in dirs]

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
        UnionRule(GenerateTargetsRequest, GenerateTargetsFromNfpmContentSymlinksRequest),
        UnionRule(GenerateTargetsRequest, GenerateTargetsFromNfpmContentDirsRequest),
    )
