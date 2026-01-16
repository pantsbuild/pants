# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import os
from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TypeVar, cast

from pants.backend.docker.subsystems.docker_options import DockerOptions
from pants.backend.docker.util_rules.docker_build_args import DockerBuildArgs
from pants.core.util_rules.system_binaries import (
    BinaryPath,
    BinaryPathRequest,
    BinaryPathTest,
    BinaryShims,
    BinaryShimsRequest,
    create_binary_shims,
    find_binary,
)
from pants.engine.fs import Digest
from pants.engine.process import Process, ProcessCacheScope
from pants.engine.rules import collect_rules, concurrently, implicitly, rule
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize

T = TypeVar("T", bound="BaseBinary")


@dataclass(frozen=True)
class BaseBinary(BinaryPath, ABC):
    """Base class for all binary paths."""

    global_options: tuple[str, ...]
    extra_env: Mapping[str, str]
    extra_input_digests: Mapping[str, Digest] | None

    def __init__(
        self,
        path: str,
        fingerprint: str | None = None,
        global_options: tuple[str, ...] = (),
        extra_env: Mapping[str, str] | None = None,
        extra_input_digests: Mapping[str, Digest] | None = None,
    ) -> None:
        object.__setattr__(self, "global_options", global_options)
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

    @abstractmethod
    def build_image(
        self,
        tags: tuple[str, ...],
        digest: Digest,
        dockerfile: str,
        build_args: DockerBuildArgs,
        context_root: str,
        env: Mapping[str, str],
        extra_args: tuple[str, ...] = (),
    ) -> Process: ...


class _DockerPodmanMixin(BaseBinary):
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
        args = [self.path, *self.global_options, "build", *extra_args]

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
                + (f" +{pluralize(len(tags) - 1, 'additional tag')}." if len(tags) > 1 else "")
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
            argv=(self.path, *self.global_options, "push", tag),
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
            argv=(
                self.path,
                *self.global_options,
                "run",
                *(docker_run_args or []),
                tag,
                *(image_args or []),
            ),
            cache_scope=ProcessCacheScope.PER_SESSION,
            description=f"Running docker image {tag}",
            env=self._get_process_environment(env or {}),
            immutable_input_digests=self.extra_input_digests,
        )


class DockerBinary(_DockerPodmanMixin):
    """The `docker` binary."""


class PodmanBinary(_DockerPodmanMixin):
    """The `podman` binary."""


class BuildctlBinary(BaseBinary):
    """The `buildctl` binary."""

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
        args = [
            self.path,
            *self.global_options,
            "build",
            "--frontend",
            "dockerfile.v0",
            "--local",
            f"context={context_root}",
            "--local",
            f"dockerfile={os.path.dirname(dockerfile)}",
            "--opt",
            f"filename={os.path.basename(dockerfile)}",
            *extra_args,
        ]

        for build_arg in build_args:
            args.extend(["--opt", f"build-arg:{build_arg}"])

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


async def _get_docker_tools_shims(
    *,
    tools: Sequence[str],
    optional_tools: Sequence[str],
    search_path: Sequence[str],
    rationale: str,
) -> BinaryShims:
    all_binary_first_paths: list[BinaryPath] = []

    if tools:
        tools_requests = [
            BinaryPathRequest(binary_name=binary_name, search_path=search_path)
            for binary_name in tools
        ]

        tools_paths = await concurrently(
            find_binary(tools_request, **implicitly()) for tools_request in tools_requests
        )

        all_binary_first_paths.extend(
            [
                path.first_path_or_raise(request, rationale=rationale)
                for request, path in zip(tools_requests, tools_paths)
            ]
        )

    if optional_tools:
        optional_tools_requests = [
            BinaryPathRequest(binary_name=binary_name, search_path=search_path)
            for binary_name in optional_tools
        ]

        optional_tools_paths = await concurrently(
            find_binary(optional_tools_request, **implicitly())
            for optional_tools_request in optional_tools_requests
        )

        all_binary_first_paths.extend(
            [
                cast(BinaryPath, path.first_path)  # safe since we check for non-empty paths below
                for path in optional_tools_paths
                if path.paths
            ]
        )

    tools_shims = await create_binary_shims(
        BinaryShimsRequest.for_paths(
            *all_binary_first_paths,
            rationale=rationale,
        ),
        **implicitly(),
    )

    return tools_shims


async def get_binary(
    binary_name: str,
    binary_cls: type[T],
    docker_options: DockerOptions,
    docker_options_env_aware: DockerOptions.EnvironmentAware,
) -> T:
    search_path = docker_options_env_aware.executable_search_path

    request = BinaryPathRequest(
        binary_name=binary_name,
        search_path=search_path,
        test=BinaryPathTest(args=["-v"]),
    )
    paths = await find_binary(request, **implicitly())
    first_path = paths.first_path_or_raise(request, rationale="interact with the docker daemon")

    if not docker_options.tools and not docker_options.optional_tools:
        return binary_cls(
            first_path.path, first_path.fingerprint, global_options=docker_options.global_options
        )

    tools_shims = await _get_docker_tools_shims(
        tools=docker_options.tools,
        optional_tools=docker_options.optional_tools,
        search_path=search_path,
        rationale=f"use {binary_name}",
    )
    return binary_cls(
        first_path.path,
        first_path.fingerprint,
        global_options=docker_options.global_options,
        extra_env={"PATH": tools_shims.path_component},
        extra_input_digests=tools_shims.immutable_input_digests,
    )


@rule(desc="Finding the `docker` binary and related tooling", level=LogLevel.DEBUG)
async def get_docker(
    docker_options: DockerOptions, docker_options_env_aware: DockerOptions.EnvironmentAware
) -> DockerBinary:
    return await get_binary("docker", DockerBinary, docker_options, docker_options_env_aware)


@rule(desc="Finding the `podman` binary and related tooling", level=LogLevel.DEBUG)
async def get_podman(
    docker_options: DockerOptions, docker_options_env_aware: DockerOptions.EnvironmentAware
) -> PodmanBinary:
    return await get_binary("podman", PodmanBinary, docker_options, docker_options_env_aware)


@rule(desc="Finding the `buildctl` binary and related tooling", level=LogLevel.DEBUG)
async def get_buildctl(
    docker_options: DockerOptions, docker_options_env_aware: DockerOptions.EnvironmentAware
) -> BuildctlBinary:
    return await get_binary("buildctl", BuildctlBinary, docker_options, docker_options_env_aware)


def rules():
    return collect_rules()
