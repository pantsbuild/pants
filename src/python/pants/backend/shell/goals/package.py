# Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import dataclasses
import os
from collections.abc import Iterable
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
from pants.engine.intrinsics import add_prefix, get_digest_entries
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


def _close_over_parent_paths(paths: Iterable[str]) -> frozenset[str]:
    result: set[str] = set()
    for path in paths:
        path_parts = path.split(os.sep)
        i = 1
        while i <= len(path_parts):
            result.add(os.path.join(*path_parts[0:i]))
            i += 1
    return frozenset(result)


@rule(desc="Package with shell command", level=LogLevel.DEBUG)
async def package_shell_command(
    field_set: PackageShellCommandFieldSet,
) -> BuiltPackage:
    wrapped_tgt = await resolve_target(
        WrappedTargetRequest(field_set.address, description_of_origin="<infallible>"),
        **implicitly(),
    )
    target = wrapped_tgt.target

    shell_process = await prepare_process_request_from_target(
        ShellCommandProcessFromTargetRequest(target), **implicitly()
    )

    shell_process = dataclasses.replace(
        shell_process,
        cache_scope=shell_process.cache_scope or ProcessCacheScope.SUCCESSFUL,
    )

    result = await run_prepared_adhoc_process(**implicitly({shell_process: AdhocProcessRequest}))

    if result.process_result.exit_code != 0:
        raise ValueError(
            f"The `{target.alias}` at `{field_set.address}` failed with exit code {result.process_result.exit_code}.\n\n"
            f"stdout:\n\n{result.process_result.stdout.decode(errors='ignore')}\n\n"
            f"stderr:\n\n{result.process_result.stderr.decode(errors='ignore')}"
        )

    if result.adjusted_digest == EMPTY_DIGEST:
        raise ValueError(
            f"The `{target.alias}` at `{field_set.address}` did not produce or capture any output. "
            "The `package` goal is expected to produce output."
        )

    # First, validate that packaged_artifacts exist in the output (before applying output_path).
    output_digest_entries = await get_digest_entries(result.adjusted_digest)
    captured_paths = _close_over_parent_paths(e.path for e in output_digest_entries)
    configured_packaged_artifacts = field_set.packaged_artifacts.value or ()
    validated_packaged_artifacts: list[str] = []
    missing_packaged_artifacts: list[str] = []
    for packaged_artifact in configured_packaged_artifacts:
        if packaged_artifact in captured_paths:
            if packaged_artifact not in validated_packaged_artifacts:
                validated_packaged_artifacts.append(packaged_artifact)
        else:
            missing_packaged_artifacts.append(packaged_artifact)

    # Raise an error for any `packaged_artifacts` entries not present in the output.
    if missing_packaged_artifacts:
        missing_packaged_artifacts_str = ", ".join(missing_packaged_artifacts)
        raise ValueError(
            f"The following `packaged_artifacts` for the `{target.alias}` at `{field_set.address}` did not match "
            f"any file or directory in the captured output: {missing_packaged_artifacts_str}"
        )

    # Apply the output path for the artifacts.
    output_path = field_set.output_path.value_or_default(file_ending=None)
    output_digest: Digest
    if output_path:
        output_digest = await add_prefix(AddPrefix(result.adjusted_digest, output_path))
    else:
        output_digest = result.adjusted_digest

    # Create artifacts list with output_path applied to validated artifacts. If no artifacts were specified, then
    # just make a single `BuiltPackageArtifact` for the entire output path.
    artifacts: list[BuiltPackageArtifact] = []
    if configured_packaged_artifacts:
        for packaged_artifact in validated_packaged_artifacts:
            relpath = (
                os.path.join(output_path, packaged_artifact) if output_path else packaged_artifact
            )
            artifacts.append(BuiltPackageArtifact(relpath=relpath))
    else:
        if not output_path:
            raise AssertionError(
                f"No `packaged_artifacts` for the `{target.alias}` at `{field_set.address}` were configured and the "
                "`output_path` is empty which means we cannot configure the internal `BuiltPackageArtifact` instance needed."
            )
        artifacts.append(BuiltPackageArtifact(relpath=output_path))

    return BuiltPackage(output_digest, tuple(artifacts))


def rules():
    return (
        *collect_rules(),
        *shell_command.rules(),
        *adhoc_process_support_rules(),
        UnionRule(PackageFieldSet, PackageShellCommandFieldSet),
    )
