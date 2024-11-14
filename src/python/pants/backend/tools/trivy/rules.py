# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from dataclasses import dataclass

from pants.backend.tools.trivy.subsystem import Trivy
from pants.core.goals.resolves import ExportableTool
from pants.core.util_rules import external_tool
from pants.core.util_rules.external_tool import download_external_tool
from pants.engine.env_vars import EnvironmentVars, EnvironmentVarsRequest
from pants.engine.internals.native_engine import Digest
from pants.engine.internals.selectors import Get
from pants.engine.intrinsics import execute_process
from pants.engine.platform import Platform
from pants.engine.process import FallibleProcessResult, Process
from pants.engine.rules import collect_rules, rule
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel


@dataclass(frozen=True)
class RunTrivyRequest:
    # trivy fields
    command: str
    scanners: tuple[str, ...]
    target: str
    # pants fields
    input_digest: Digest
    description: str


# TODO: capture output file?
# TODO: config files
# TODO: report format
# TODO: exit code options


@rule
async def run_trivy(
    request: RunTrivyRequest,
    trivy: Trivy,
    platform: Platform,
) -> FallibleProcessResult:
    """Run Trivy."""
    argv = ["__trivy/trivy", "-d", "--format=table", "--exit-code=1"]

    # workaround for Trivy DB being overloaded on pulls
    argv.extend(
        ["--db-repository", "ghcr.io/aquasecurity/trivy-db,public.ecr.aws/aquasecurity/trivy-db"]
    )

    argv.extend(["--cache-dir", trivy.cache_dir])

    argv.append(request.command)

    if request.scanners:
        argv.append("--scanners")
        argv.append(",".join(request.scanners))

    argv.append(request.target)

    argv.append("--no-progress")  # quiet progress output, which just clutters logs

    argv.extend(trivy.args)

    download_trivy = await download_external_tool(trivy.get_request(platform))

    env = await Get(EnvironmentVars, EnvironmentVarsRequest(trivy.extra_env_vars))

    immutable_input_digests = {"__trivy": download_trivy.digest}

    result = await execute_process(
        Process(
            argv=tuple(argv),
            input_digest=request.input_digest,
            immutable_input_digests=immutable_input_digests,
            append_only_caches=trivy.append_only_caches,
            env=env,
            description=request.description,
            level=LogLevel.DEBUG,
        )
    )
    return result


def rules():
    return (
        *collect_rules(),
        *external_tool.rules(),
        UnionRule(ExportableTool, Trivy),
    )
