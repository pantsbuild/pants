# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from pants.backend.docker.subsystems.docker_options import DockerOptions
from pants.backend.docker.util_rules.docker_build_args import DockerBuildArgs
from pants.core.util_rules.system_binaries import (
    BinaryPath,
    BinaryPathRequest,
    BinaryPathTest,
    find_binary,
)
from pants.engine.fs import Digest
from pants.engine.process import Process, ProcessCacheScope
from pants.engine.rules import collect_rules, implicitly, rule
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize

from .docker_binary import _get_docker_tools_shims


@dataclass(frozen=True)
class BuildctlBinary(BinaryPath):
    """The `buildctl` binary."""

    extra_env: Mapping[str, str]
    extra_input_digests: Mapping[str, Digest] | None

    def __init__(
        self,
        path: str,
        fingerprint: str | None = None,
        extra_env: Mapping[str, str] | None = None,
        extra_input_digests: Mapping[str, Digest] | None = None,
    ) -> None:
        object.__setattr__(self, "extra_env", {} if extra_env is None else extra_env)
        object.__setattr__(self, "extra_input_digests", extra_input_digests)
        super().__init__(path, fingerprint)

    def _get_process_environment(self, env: Mapping[str, str]) -> Mapping[str, str]:
        if not self.extra_env:
            return env

        res = {**self.extra_env, **env}

        # Merge the PATH entries, in case they are present in both `env` and `self.extra_env`.
        res["PATH"] = os.pathsep.join(
            p for p in (m.get("PATH") for m in (self.extra_env, env)) if p
        )
        return res

    def build_image(
        self,
        tags: tuple[str, ...],
        digest: Digest,
        dockerfile: Path,
        build_args: DockerBuildArgs,
        context_root: str,
        env: Mapping[str, str],
        target_stage: str | None = None,
        extra_args: tuple[str, ...] = (),
    ) -> Process:
        args = [
            self.path,
            *extra_args,
            "build",
            "--frontend",
            "dockerfile.v0",
            "--local",
            f"context={context_root}",
            "--local",
            f"dockerfile={dockerfile.parent}",
            "--opt",
            f"filename={dockerfile.name}",
        ]

        for build_arg in build_args:
            args.extend(["--opt", f"build-arg:{build_arg}"])

        if target_stage:
            args.extend(["--opt", f"--target={target_stage}"])

        for tag in tags:
            args.extend(["--output", f"type=image,name={tag},push=true"])

        return Process(
            argv=tuple(args),
            description=(
                f"Building docker image {tags[0]}"
                + (f" +{pluralize(len(tags) - 1, 'additional tag')}." if len(tags) > 1 else "")
            ),
            env=self._get_process_environment(env),
            input_digest=digest,
            immutable_input_digests=self.extra_input_digests,
            cache_scope=ProcessCacheScope.PER_SESSION,
        )


@rule(desc="Finding the `buildctl` binary and related tooling", level=LogLevel.DEBUG)
async def get_docker(
    docker_options: DockerOptions, docker_options_env_aware: DockerOptions.EnvironmentAware
) -> BuildctlBinary:
    search_path = docker_options_env_aware.executable_search_path

    request = BinaryPathRequest(
        binary_name="buildctl",
        search_path=search_path,
        test=BinaryPathTest(args=["-v"]),
    )
    paths = await find_binary(request, **implicitly())
    first_path = paths.first_path_or_raise(request, rationale="interact with the docker daemon")

    if not docker_options.tools and not docker_options.optional_tools:
        return BuildctlBinary(first_path.path, first_path.fingerprint)

    tools_shims = await _get_docker_tools_shims(
        tools=docker_options.tools,
        optional_tools=docker_options.optional_tools,
        search_path=search_path,
        rationale="use docker",
    )

    extra_env = {"PATH": tools_shims.path_component}
    extra_input_digests = tools_shims.immutable_input_digests

    return BuildctlBinary(
        first_path.path,
        first_path.fingerprint,
        extra_env=extra_env,
        extra_input_digests=extra_input_digests,
    )


def rules():
    return collect_rules()
