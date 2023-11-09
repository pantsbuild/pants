# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass

import yaml

from pants.backend.nfpm.config import NfpmContent, file_info
from pants.backend.nfpm.field_sets import NfpmPackageFieldSet
from pants.backend.nfpm.fields.all import NfpmDependencies
from pants.backend.nfpm.fields.contents import (
    NfpmContentDirDstField,
    NfpmContentDstField,
    NfpmContentFileSourceField,
    NfpmContentSrcField,
    NfpmContentSymlinkDstField,
    NfpmContentSymlinkSrcField,
    NfpmContentTypeField,
)
from pants.backend.nfpm.target_types import NfpmContentFile
from pants.core.goals.package import TraverseIfNotPackageTarget
from pants.engine.fs import CreateDigest, DigestEntries, FileContent, FileEntry
from pants.engine.internals.native_engine import Digest
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.target import TransitiveTargets, TransitiveTargetsRequest
from pants.engine.unions import UnionMembership
from pants.util.logging import LogLevel
from pants.util.strutil import softwrap


@dataclass(frozen=True)
class NfpmPackageConfigRequest:
    field_set: NfpmPackageFieldSet
    content_sandbox_digest: Digest  # NfpmContentSandbox.digest


@dataclass(frozen=True)
class NfpmPackageConfig:
    digest: Digest  # digest contains nfpm.yaml


class InvalidNfpmContentFileTargetsException(Exception):
    pass


class NfpmSrcMissingFromSandboxException(Exception):
    pass


@rule(level=LogLevel.DEBUG)
async def generate_nfpm_yaml(
    request: NfpmPackageConfigRequest, union_membership: UnionMembership
) -> NfpmPackageConfig:
    transitive_targets = await Get(
        TransitiveTargets,
        TransitiveTargetsRequest(
            [request.field_set.address],
            should_traverse_deps_predicate=TraverseIfNotPackageTarget(
                roots=[request.field_set.address],
                union_membership=union_membership,
            ),
        ),
    )

    # Fist get the config that can be constructed from the target itself.
    nfpm_package_target = transitive_targets.roots[0]
    config = request.field_set.nfpm_config(nfpm_package_target)

    # Second, gather package contents from hydrated deps.
    contents: list[NfpmContent] = config["contents"]

    content_sandbox_entries = await Get(DigestEntries, Digest, request.content_sandbox_digest)
    content_sandbox_files = {
        entry.path: entry for entry in content_sandbox_entries if isinstance(entry, FileEntry)
    }

    invalid_content_file_targets = []
    src_missing_from_sandbox = []

    # NB: TransitiveTargets is AFTER target generation/expansion (so there are no target generators)
    for tgt in transitive_targets.dependencies:
        if tgt.has_field(NfpmContentDirDstField):  # an NfpmContentDir
            contents.append(
                NfpmContent(
                    type="dir",
                    dst=tgt[NfpmContentDirDstField].value,
                    file_info=file_info(tgt),
                )
            )
        elif tgt.has_field(NfpmContentSymlinkDstField):  # an NfpmContentSymlink
            contents.append(
                NfpmContent(
                    type="symlink",
                    src=tgt[NfpmContentSymlinkSrcField].value,
                    dst=tgt[NfpmContentSymlinkDstField].value,
                    file_info=file_info(tgt),
                )
            )
        elif tgt.has_field(NfpmContentDstField):  # an NfpmContentFile
            source: str | None = tgt[NfpmContentFileSourceField].value
            src: str | None = tgt[NfpmContentSrcField].value
            dst: str = tgt[NfpmContentDstField].value
            if source is not None and not src:
                # If defined, 'source' provides the default value for 'src'.
                src = source
            if src is None:  # src is NOT required; prepare to raise an error.
                invalid_content_file_targets.append(tgt)
                continue
            sandbox_file: FileEntry | None = content_sandbox_files.get(src)
            if sandbox_file is None:
                src_missing_from_sandbox.append(tgt)
                continue
            contents.append(
                NfpmContent(
                    type=tgt[NfpmContentTypeField].value,
                    src=src,
                    dst=dst,
                    file_info=file_info(tgt, sandbox_file.is_executable),
                )
            )

    if invalid_content_file_targets:
        plural = len(invalid_content_file_targets) > 1
        raise InvalidNfpmContentFileTargetsException(
            softwrap(
                f"""
                The '{NfpmContentFile.alias}' target type requires a value for the '{NfpmContentSrcField.alias}' field,
                But {'these targets are' if plural else 'this target is'} missing a '{NfpmContentSrcField.alias}' value.
                If the '{NfpmContentFileSourceField.alias}' field is provided, then the '{NfpmContentSrcField.alias}'
                defaults to the file referenced in the '{NfpmContentFileSourceField.alias}' field.
                Please fix the {'targets at these addresses' if plural else 'target at this address'}:
                """
                + ",\n".join(tgt.address for tgt in invalid_content_file_targets)
            )
        )
    if src_missing_from_sandbox:
        plural = len(src_missing_from_sandbox) > 1
        raise NfpmSrcMissingFromSandboxException(
            softwrap(
                f"""
                The '{NfpmContentSrcField.alias}' {'files are' if plural else 'file is'} missing
                from the nfpm sandbox. This sandbox contains packages, generated code, and sources
                from the '{NfpmDependencies.alias}' field. It also contains any file from the
                '{NfpmContentFileSourceField.alias}' field. Please fix the '{NfpmContentFile.alias}'
                {'targets at these addresses' if plural else 'target at this address'}.:
                """
                + ",\n".join(tgt.address for tgt in src_missing_from_sandbox)
            )
        )

    contents.sort(key=lambda d: d["dst"])

    scripts = request.field_set.scripts.value or {}
    script_src_missing_from_sandbox = {
        script_type: script_src
        for script_type, script_src in scripts.items()
        if content_sandbox_files.get(script_src) is None
    }
    if script_src_missing_from_sandbox:
        plural = len(script_src_missing_from_sandbox) > 1
        raise NfpmSrcMissingFromSandboxException(
            softwrap(
                f"""
                {request.field_set.address}: {'Some' if plural else 'One'} of the files in the
                '{request.field_set.scripts.alias}' field {'are' if plural else 'is'} missing
                from the nfpm sandbox. The sandbox gets populated from the '{NfpmDependencies.alias}'
                field. Are you missing {'any dependencies' if plural else 'a dependency'}?
                Here {'are' if plural else 'is'} the missing {'scripts' if plural else 'script'}:
                {repr(script_src_missing_from_sandbox)}
                """
            )
        )

    nfpm_yaml = "# Generated by Pantsbuild\n"
    nfpm_yaml += yaml.safe_dump(config)
    nfpm_yaml_content = FileContent("nfpm.yaml", nfpm_yaml.encode())

    digest = await Get(Digest, CreateDigest([nfpm_yaml_content]))
    return NfpmPackageConfig(digest)


def rules():
    return [*collect_rules()]
