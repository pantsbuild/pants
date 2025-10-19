# Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import dataclasses
from dataclasses import dataclass

from pants.backend.shell.target_types import (
    ShellCommandCommandField,
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

    # Apply the output path for the artifacts.
    output_path = field_set.output_path.value_or_default(file_ending=None)
    output_digest: Digest
    if output_path:
        output_digest = await add_prefix(AddPrefix(result.adjusted_digest, output_path))
    else:
        output_digest = result.adjusted_digest

    output_digest_entries = await get_digest_entries(result.adjusted_digest)
    file_paths = sorted(e.path for e in output_digest_entries)
    artifacts = tuple(BuiltPackageArtifact(relpath=path) for path in file_paths)
    return BuiltPackage(output_digest, artifacts)


def rules():
    return (
        *collect_rules(),
        *shell_command.rules(),
        *adhoc_process_support_rules(),
        UnionRule(PackageFieldSet, PackageShellCommandFieldSet),
    )
