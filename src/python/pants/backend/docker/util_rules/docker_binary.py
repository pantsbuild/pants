# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Mapping

from pants.backend.docker.subsystems.docker_options import DockerOptions
from pants.backend.docker.util_rules.docker_build_args import DockerBuildArgs
from pants.core.util_rules.system_binaries import (
    BinaryPath,
    BinaryPathRequest,
    BinaryPaths,
    BinaryPathTest,
    BinaryShims,
    BinaryShimsRequest,
)
from pants.engine.fs import Digest
from pants.engine.process import Process, ProcessCacheScope
from pants.engine.rules import Get, collect_rules, rule
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DockerBinary(BinaryPath):
    """The `docker` binary."""

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
        dockerfile: str,
        build_args: DockerBuildArgs,
        context_root: str,
        env: Mapping[str, str],
        use_buildx: bool,
        extra_args: tuple[str, ...] = (),
    ) -> Process:
        if use_buildx:
            build_commands = ["buildx", "build"]
        else:
            build_commands = ["build"]

        args = [self.path, *build_commands, *extra_args]

        for tag in tags:
            args.extend(["--tag", tag])

        for build_arg in build_args:
            args.extend(["--build-arg", build_arg])

        args.extend(["--file", dockerfile])

        # Docker context root.
        args.append(context_root)

        return Process(
            argv=tuple(args),
            description=(
                f"Building docker image {tags[0]}"
                + (f" +{pluralize(len(tags)-1, 'additional tag')}." if len(tags) > 1 else "")
            ),
            env=self._get_process_environment(env),
            input_digest=digest,
            immutable_input_digests=self.extra_input_digests,
            # We must run the docker build commands every time, even if nothing has changed,
            # in case the user ran `docker image rm` outside of Pants.
            cache_scope=ProcessCacheScope.PER_SESSION,
        )

    def push_image(self, tag: str, env: Mapping[str, str] | None = None) -> Process:
        return Process(
            argv=(self.path, "push", tag),
            cache_scope=ProcessCacheScope.PER_SESSION,
            description=f"Pushing docker image {tag}",
            env=self._get_process_environment(env or {}),
            immutable_input_digests=self.extra_input_digests,
        )

    def run_image(
        self,
        tag: str,
        *,
        docker_run_args: tuple[str, ...] | None = None,
        image_args: tuple[str, ...] | None = None,
        env: Mapping[str, str] | None = None,
    ) -> Process:
        return Process(
            argv=(self.path, "run", *(docker_run_args or []), tag, *(image_args or [])),
            cache_scope=ProcessCacheScope.PER_SESSION,
            description=f"Running docker image {tag}",
            env=self._get_process_environment(env or {}),
            immutable_input_digests=self.extra_input_digests,
        )


@rule(desc="Finding the `docker` binary and related tooling", level=LogLevel.DEBUG)
async def get_docker(
    docker_options: DockerOptions, docker_options_env_aware: DockerOptions.EnvironmentAware
) -> DockerBinary:
    search_path = docker_options_env_aware.executable_search_path

    first_path: BinaryPath | None = None

    if docker_options.enable_podman:
        request = BinaryPathRequest(
            binary_name="podman",
            search_path=search_path,
            test=BinaryPathTest(args=["-v"]),
        )
        paths = await Get(BinaryPaths, BinaryPathRequest, request)
        first_path = paths.first_path
        if first_path:
            logger.warning("podman found. Podman support is experimental.")

    if not first_path:
        request = BinaryPathRequest(
            binary_name="docker",
            search_path=search_path,
            test=BinaryPathTest(args=["-v"]),
        )
        paths = await Get(BinaryPaths, BinaryPathRequest, request)
        first_path = paths.first_path_or_raise(request, rationale="interact with the docker daemon")

    if not docker_options.tools:
        return DockerBinary(first_path.path, first_path.fingerprint)

    tools = await Get(
        BinaryShims,
        BinaryShimsRequest,
        BinaryShimsRequest.for_binaries(
            *docker_options.tools,
            rationale="use docker",
            search_path=search_path,
        ),
    )
    extra_env = {"PATH": tools.path_component}
    extra_input_digests = tools.immutable_input_digests

    return DockerBinary(
        first_path.path,
        first_path.fingerprint,
        extra_env=extra_env,
        extra_input_digests=extra_input_digests,
    )


def rules():
    return collect_rules()
