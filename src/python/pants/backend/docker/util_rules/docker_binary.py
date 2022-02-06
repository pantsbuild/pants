# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping

from pants.backend.docker.subsystems.docker_options import DockerOptions
from pants.backend.docker.util_rules.docker_build_args import DockerBuildArgs
from pants.core.util_rules.system_binaries import (
    BinaryNotFoundError,
    BinaryPath,
    BinaryPathRequest,
    BinaryPaths,
    BinaryPathTest,
)
from pants.engine.environment import Environment, EnvironmentRequest
from pants.engine.fs import Digest
from pants.engine.process import Process, ProcessCacheScope
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize


# The base class is decorated with `frozen_after_init`.
@dataclass
class DockerBinary(BinaryPath):
    """The `docker` binary."""

    extra_env: Mapping[str, str]

    def __init__(
        self, path: str, fingerprint: str | None = None, extra_env: Mapping[str, str] | None = None
    ) -> None:
        self.extra_env = {} if extra_env is None else extra_env
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
        extra_args: tuple[str, ...] = (),
    ) -> Process:
        args = [self.path, "build", *extra_args]

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
            cache_scope=ProcessCacheScope.PER_SESSION,
        )

    def push_image(
        self, tags: tuple[str, ...], env: Mapping[str, str] | None = None
    ) -> tuple[Process, ...]:
        return tuple(
            Process(
                argv=(self.path, "push", tag),
                cache_scope=ProcessCacheScope.PER_SESSION,
                description=f"Pushing docker image {tag}",
                env=self._get_process_environment(env or {}),
            )
            for tag in tags
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
        )


@dataclass(frozen=True)
class DockerBinaryRequest:
    pass


@rule(desc="Finding the `docker` binary and related tooling", level=LogLevel.DEBUG)
async def find_docker(
    docker_request: DockerBinaryRequest, docker_options: DockerOptions
) -> DockerBinary:
    env = await Get(Environment, EnvironmentRequest(["PATH"]))
    search_path = docker_options.executable_search_path(env)
    requests = [
        BinaryPathRequest(
            binary_name=tool,
            search_path=search_path,
            test=BinaryPathTest(args=["-v"]) if tool == "docker" else None,
        )
        for tool in {"docker", *docker_options.tools}
    ]
    binary_paths = await MultiGet(
        Get(BinaryPaths, BinaryPathRequest, request) for request in requests
    )

    found_paths = []
    for binary, request in zip(binary_paths, requests):
        if binary.first_path:
            found_paths.append(binary.first_path)
        else:
            raise BinaryNotFoundError.from_request(
                request,
                rationale="interact with the docker daemon",
            )

    return DockerBinary(
        found_paths[0].path,
        found_paths[0].fingerprint,
        extra_env=(
            {"PATH": os.pathsep.join({os.path.dirname(found.path) for found in found_paths[1:]})}
            if len(found_paths) > 1
            else None
        ),
    )


@rule
async def get_docker() -> DockerBinary:
    return await Get(DockerBinary, DockerBinaryRequest())


def rules():
    return collect_rules()
