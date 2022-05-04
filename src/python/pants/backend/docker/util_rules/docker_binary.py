# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import textwrap
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
from pants.engine.environment import Environment, EnvironmentRequest
from pants.engine.fs import CreateDigest, Digest, FileContent
from pants.engine.internals.native_engine import MergeDigests
from pants.engine.process import Process, ProcessCacheScope
from pants.engine.rules import Get, collect_rules, rule
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize


# The base class is decorated with `frozen_after_init`.
@dataclass
class DockerBinary(BinaryPath):
    """The `docker` binary."""

    extra_input_digests: Mapping[str, Digest] | None

    def __init__(
        self,
        path: str,
        fingerprint: str | None = None,
        extra_input_digests: Mapping[str, Digest] | None = None,
    ) -> None:
        self.extra_input_digests = extra_input_digests
        super().__init__(path, fingerprint)

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
            env=env or {},
            input_digest=digest,
            immutable_input_digests=self.extra_input_digests,
            cache_scope=ProcessCacheScope.PER_SESSION,
        )

    def push_image(self, tag: str, env: Mapping[str, str] | None = None) -> Process:
        return Process(
            argv=(self.path, "push", tag),
            cache_scope=ProcessCacheScope.PER_SESSION,
            description=f"Pushing docker image {tag}",
            env=env or {},
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
            env=env or {},
            immutable_input_digests=self.extra_input_digests,
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
    request = BinaryPathRequest(
        binary_name="docker",
        search_path=search_path,
        test=BinaryPathTest(args=["-v"]),
    )
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="interact with the docker daemon")

    if not docker_options.tools:
        return DockerBinary(first_path.path, first_path.fingerprint)

    tools_path = ".shims"
    tools = await Get(
        BinaryShims,
        BinaryShimsRequest,
        BinaryShimsRequest.for_binaries(
            *docker_options.tools,
            rationale="use docker",
            output_directory="bin",
            search_path=search_path,
        ),
    )

    # In addition to the docker-tool shims we generate above, we generate a shim for the
    # `docker` CLI itself. This shim ensures that the _absolute path_ to the `.shim/bin`
    # directory populated above is on the `PATH` for the CLI.
    #
    # It's important that we use the absolute path to `.shims/bin` because the use of a
    # relative path raises an error. The error comes from the `LookPath` function in the
    # `golang.org/x/sys/execabs` package, which the `docker` CLI started using as of
    # https://github.com/docker/cli/commit/8d199d5bba9db46b6610bd959d815ce7197402b3. The
    # error condition was added purposefully by the core Go team, and it's since been
    # ported to `os/exec` in the Go stdlib (see https://github.com/golang/go/issues/43724).
    #
    # Using a shim script for the docker CLI here is ugly, but as far as I can tell it's
    # the only way to dynamically invoke/inject the value of `$(pwd)` for the docker processes
    # into an env value. Trying to set `{"PATH": "$(pwd)/.shims/bin"}` in the `env` field
    # for the returned `DockerBinary` instance doesn't work because the values in that map
    # are shell-escaped before they are written to `__run.sh`.
    docker_shim_script = FileContent(
        "__run_docker.sh",
        textwrap.dedent(
            f"""\
            #!/bin/bash
            export PATH="$(pwd)/{tools_path}/{tools.bin_directory}:${{PATH}}"
            exec "{first_path.path}" "${{@}}"
            """
        ).encode("utf-8"),
        is_executable=True,
    )
    docker_shim_digest = await Get(Digest, CreateDigest([docker_shim_script]))

    shims_digest = await Get(Digest, MergeDigests([tools.digest, docker_shim_digest]))
    extra_input_digests = {tools_path: shims_digest}

    return DockerBinary(
        f"{tools_path}/{docker_shim_script.path}",
        first_path.fingerprint,
        extra_input_digests=extra_input_digests,
    )


@rule
async def get_docker() -> DockerBinary:
    return await Get(DockerBinary, DockerBinaryRequest())


def rules():
    return collect_rules()
