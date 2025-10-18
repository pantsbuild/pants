# Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import dataclasses
import os
from dataclasses import dataclass

from pants.backend.shell.target_types import (
    ShellCommandCommandField,
    ShellCommandPackagedArtifactsField,
    ShellCommandPackageDependenciesField,
    SkipShellCommandPackageField,
)
from pants.backend.shell.util_rules import shell_command
from pants.backend.shell.util_rules.shell_command import (
    ShellCommandProcessFromTargetRequest,
    prepare_process_request_from_target,
)
from pants.core.environments.target_types import EnvironmentField
from pants.core.goals.package import (
    BuiltPackage,
    BuiltPackageArtifact,
    OutputPathField,
    PackageFieldSet,
)
from pants.core.util_rules.adhoc_process_support import AdhocProcessRequest
from pants.core.util_rules.adhoc_process_support import rules as adhoc_process_support_rules
from pants.core.util_rules.adhoc_process_support import run_prepared_adhoc_process
from pants.engine.fs import EMPTY_DIGEST, AddPrefix, Digest
from pants.engine.internals.graph import resolve_target
from pants.engine.intrinsics import add_prefix, digest_to_snapshot
from pants.engine.process import ProcessCacheScope
from pants.engine.rules import collect_rules, implicitly, rule
from pants.engine.target import Target, WrappedTargetRequest
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel


@dataclass(frozen=True)
class PackageShellCommandFieldSet(PackageFieldSet):
    required_fields = (
        ShellCommandCommandField,
        ShellCommandPackageDependenciesField,
    )

    environment: EnvironmentField
    output_path: OutputPathField
    packaged_artifacts: ShellCommandPackagedArtifactsField

    @classmethod
    def opt_out(cls, tgt: Target) -> bool:
        return tgt.get(SkipShellCommandPackageField).value


@rule(desc="Package with shell command", level=LogLevel.DEBUG)
async def package_shell_command(
    field_set: PackageShellCommandFieldSet,
) -> BuiltPackage:
    wrapped_tgt = await resolve_target(
        WrappedTargetRequest(field_set.address, description_of_origin="<infallible>"),
        **implicitly(),
    )

    shell_process = await prepare_process_request_from_target(
        ShellCommandProcessFromTargetRequest(wrapped_tgt.target), **implicitly()
    )

    shell_process = dataclasses.replace(
        shell_process,
        cache_scope=shell_process.cache_scope or ProcessCacheScope.SUCCESSFUL,
    )

    result = await run_prepared_adhoc_process(**implicitly({shell_process: AdhocProcessRequest}))

    if result.process_result.exit_code != 0:
        raise Exception(
            f"Package command for {field_set.address} failed with exit code "
            f"{result.process_result.exit_code}"
        )

    # First, validate that packaged_artifacts exist in the output (before applying output_path).
    snapshot = await digest_to_snapshot(result.adjusted_digest)
    validated_artifacts: list[str] = []
    for packaged_artifact in field_set.packaged_artifacts.value or ():
        if packaged_artifact in snapshot.files or packaged_artifact in snapshot.dirs:
            validated_artifacts.append(packaged_artifact)

    # If no specific artifacts found, flag as an error.
    if not validated_artifacts:
        raise ValueError(
            f"None of the `packaged_artifacts` in target {field_set.address} matched any file or directory in the captured output."
        )

    # Apply the output path for the artifacts.
    output_path = field_set.output_path.value_or_default(file_ending=None)
    output_digest: Digest
    if output_path:
        output_digest = await add_prefix(AddPrefix(result.adjusted_digest, output_path))
    else:
        output_digest = result.adjusted_digest

    if output_digest == EMPTY_DIGEST:
        raise ValueError(
            f"Package command for {field_set.address} did not produce or capture any outputs."
        )

    # Create artifacts list with output_path applied to validated artifacts.
    artifacts: list[BuiltPackageArtifact] = []
    for packaged_artifact in validated_artifacts:
        relpath = os.path.join(output_path, packaged_artifact) if output_path else packaged_artifact
        artifacts.append(BuiltPackageArtifact(relpath=relpath))

    return BuiltPackage(output_digest, tuple(artifacts))


def rules():
    return (
        *collect_rules(),
        *shell_command.rules(),
        *adhoc_process_support_rules(),
        UnionRule(PackageFieldSet, PackageShellCommandFieldSet),
    )
