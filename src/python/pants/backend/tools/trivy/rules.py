# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from dataclasses import dataclass

from pants.backend.tools.trivy.subsystem import Trivy
from pants.core.goals.resolves import ExportableTool
from pants.core.util_rules import external_tool
from pants.core.util_rules.config_files import find_config_file
from pants.core.util_rules.external_tool import download_external_tool
from pants.engine.env_vars import EnvironmentVars, EnvironmentVarsRequest
from pants.engine.internals.native_engine import Digest, MergeDigests
from pants.engine.internals.selectors import Get, concurrently
from pants.engine.intrinsics import execute_process, merge_digests
from pants.engine.platform import Platform
from pants.engine.process import FallibleProcessResult, Process
from pants.engine.rules import collect_rules, implicitly, rule
from pants.engine.unions import UnionRule
from pants.option.global_options import GlobalOptions
from pants.util.logging import LogLevel


@dataclass(frozen=True)
class RunTrivyRequest:
    # trivy fields
    command: str
    command_args: tuple[str, ...]  # arguments that are command specific
    scanners: tuple[str, ...]
    target: str
    # pants fields
    input_digest: Digest
    description: str


@rule
async def run_trivy(
    request: RunTrivyRequest,
    trivy: Trivy,
    platform: Platform,
    global_options: GlobalOptions,
) -> FallibleProcessResult:
    """Run Trivy."""
    argv = ["__trivy/trivy", "--exit-code=1"]

    argv.extend(["--cache-dir", trivy.cache_dir])

    config_file = await find_config_file(trivy.config_request())
    if trivy.config:
        argv.extend(["--config", trivy.config])

    argv.append(request.command)

    if request.scanners:
        argv.append("--scanners")
        argv.append(",".join(request.scanners))

    if trivy.severity:
        argv.append("--severity")
        argv.append(",".join(trivy.severity))

    argv.append(request.target)

    argv.extend(request.command_args)

    argv.extend(trivy.args)

    if global_options.level > LogLevel.INFO:
        argv.append("-d")

    download_trivy, env, input_digest = await concurrently(
        download_external_tool(trivy.get_request(platform)),
        Get(EnvironmentVars, EnvironmentVarsRequest(trivy.extra_env_vars)),
        merge_digests(MergeDigests((request.input_digest, config_file.snapshot.digest))),
    )

    immutable_input_digests = {"__trivy": download_trivy.digest}

    result = await execute_process(
        Process(
            argv=tuple(argv),
            input_digest=input_digest,
            immutable_input_digests=immutable_input_digests,
            append_only_caches=trivy.append_only_caches,
            env=env,
            description=request.description,
            level=LogLevel.DEBUG,
        ),
        **implicitly(),
    )
    return result


def rules():
    return (
        *collect_rules(),
        *external_tool.rules(),
        UnionRule(ExportableTool, Trivy),
    )
