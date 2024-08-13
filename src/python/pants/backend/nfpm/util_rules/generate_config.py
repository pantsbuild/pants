# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass

import yaml

from pants.backend.nfpm.config import NfpmContent
from pants.backend.nfpm.field_sets import (
    NfpmContentFieldSet,
    NfpmContentFileFieldSet,
    NfpmPackageFieldSet,
)
from pants.backend.nfpm.fields.all import NfpmDependencies
from pants.backend.nfpm.fields.contents import NfpmContentFileSourceField, NfpmContentSrcField
from pants.backend.nfpm.subsystem import NfpmSubsystem
from pants.backend.nfpm.target_types import NfpmContentFile
from pants.core.goals.package import TraverseIfNotPackageTarget
from pants.engine.fs import CreateDigest, FileContent, FileEntry
from pants.engine.internals.graph import find_valid_field_sets
from pants.engine.internals.graph import transitive_targets as transitive_targets_get
from pants.engine.internals.native_engine import Digest
from pants.engine.intrinsics import create_digest_to_digest, directory_digest_to_digest_entries
from pants.engine.rules import collect_rules, implicitly, rule
from pants.engine.target import FieldSetsPerTargetRequest, TransitiveTargetsRequest
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
    request: NfpmPackageConfigRequest,
    nfpm_env_aware: NfpmSubsystem.EnvironmentAware,
    union_membership: UnionMembership,
) -> NfpmPackageConfig:
    transitive_targets = await transitive_targets_get(
        TransitiveTargetsRequest(
            [request.field_set.address],
            should_traverse_deps_predicate=TraverseIfNotPackageTarget(
                roots=[request.field_set.address],
                union_membership=union_membership,
            ),
        ),
        **implicitly(),
    )

    default_mtime = nfpm_env_aware.default_mtime

    # Fist get the config that can be constructed from the target itself.
    nfpm_package_target = transitive_targets.roots[0]
    config = request.field_set.nfpm_config(nfpm_package_target, default_mtime=default_mtime)

    # Second, gather package contents from hydrated deps.
    contents: list[NfpmContent] = config["contents"]

    content_sandbox_entries = await directory_digest_to_digest_entries(
        request.content_sandbox_digest
    )
    content_sandbox_files = {
        entry.path: entry for entry in content_sandbox_entries if isinstance(entry, FileEntry)
    }

    invalid_content_file_addresses = []
    src_missing_from_sandbox_addresses = []

    content_field_sets = await find_valid_field_sets(
        FieldSetsPerTargetRequest(NfpmContentFieldSet, transitive_targets.dependencies),
        **implicitly(),
    )

    field_set: NfpmContentFieldSet
    for field_set in content_field_sets.collection:
        try:
            nfpm_content = field_set.nfpm_config(
                content_sandbox_files=content_sandbox_files, default_mtime=default_mtime
            )
        except NfpmContentFileFieldSet.InvalidTarget:
            invalid_content_file_addresses.append(field_set.address)
            continue
        except NfpmContentFileFieldSet.SrcMissingFomSandbox:
            src_missing_from_sandbox_addresses.append(field_set.address)
            continue
        contents.append(nfpm_content)

    if invalid_content_file_addresses:
        plural = len(invalid_content_file_addresses) > 1
        raise InvalidNfpmContentFileTargetsException(
            softwrap(
                f"""
                The '{NfpmContentFile.alias}' target type requires a value for the '{NfpmContentSrcField.alias}' field,
                But {'these targets are' if plural else 'this target is'} missing a '{NfpmContentSrcField.alias}' value.
                If the '{NfpmContentFileSourceField.alias}' field is provided, then the '{NfpmContentSrcField.alias}'
                defaults to the file referenced in the '{NfpmContentFileSourceField.alias}' field.
                Please fix the {'targets at these addresses' if plural else 'target at this address'}:
                """
                + ",\n".join(str(address) for address in invalid_content_file_addresses)
            )
        )
    if src_missing_from_sandbox_addresses:
        plural = len(src_missing_from_sandbox_addresses) > 1
        raise NfpmSrcMissingFromSandboxException(
            softwrap(
                f"""
                The '{NfpmContentSrcField.alias}' {'files are' if plural else 'file is'} missing
                from the nfpm sandbox. This sandbox contains packages, generated code, and sources
                from the '{NfpmDependencies.alias}' field. It also contains any file from the
                '{NfpmContentFileSourceField.alias}' field. Please fix the '{NfpmContentFile.alias}'
                {'targets at these addresses' if plural else 'target at this address'}.:
                """
                + ",\n".join(str(address) for address in src_missing_from_sandbox_addresses)
            )
        )

    contents.sort(key=lambda d: d["dst"])

    script_src_missing_from_sandbox = {
        script_type: script_src
        for script_type, script_src in request.field_set.scripts.normalized_value.items()
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
    nfpm_yaml_content = FileContent("nfpm.yaml", nfpm_yaml.encode("utf-8"))

    digest = await create_digest_to_digest(CreateDigest([nfpm_yaml_content]))
    return NfpmPackageConfig(digest)


def rules():
    return [*collect_rules()]
