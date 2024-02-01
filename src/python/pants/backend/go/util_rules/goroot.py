# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from pants.backend.go.subsystems.golang import GolangSubsystem
from pants.backend.go.subsystems.toolchain import GoToolchain
from pants.backend.go.util_rules import go_bootstrap
from pants.backend.go.util_rules.go_bootstrap import GoBootstrap, compatible_go_version
from pants.core.util_rules.archive import ExtractedArchive
from pants.core.util_rules.environments import EnvironmentTarget
from pants.core.util_rules.system_binaries import (
    BinaryNotFoundError,
    BinaryPathRequest,
    BinaryPaths,
    BinaryPathTest,
)
from pants.engine.fs import EMPTY_DIGEST, AddPrefix, Digest, DownloadFile, RemovePrefix
from pants.engine.internals.native_engine import FileDigest
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.platform import Platform
from pants.engine.process import Process, ProcessResult
from pants.engine.rules import collect_rules, rule
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.strutil import bullet_list, softwrap, strip_v2_chroot_path_bytes

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class InstallGoToolchainRequest:
    """Request to install the Go toolchain."""


@dataclass(frozen=True)
class GoRoot:
    """Path to the Go installation (the `GOROOT`)."""

    path: str
    version: str

    _raw_metadata: FrozenDict[str, str]
    digest: Digest = EMPTY_DIGEST

    def is_compatible_version(self, version: str) -> bool:
        """Can this Go compiler handle the target version?"""
        return compatible_go_version(compiler_version=self.version, target_version=version)

    @property
    def full_version(self) -> str:
        return self._raw_metadata["GOVERSION"]

    @property
    def goos(self) -> str:
        return self._raw_metadata["GOOS"]

    @property
    def goarch(self) -> str:
        return self._raw_metadata["GOARCH"]


@rule(desc="Installing Go toolchain", level=LogLevel.DEBUG)
async def install_go_toolchain(
    req: InstallGoToolchainRequest,
    subsystem: GoToolchain,
    platform: Platform,
) -> GoRoot:
    version = subsystem.version

    external_tool = subsystem.known_version(platform)

    platform_mapping = {
        "linux_arm64": "linux-arm64",
        "linux_x86_64": "linux-amd64",
        "macos_arm64": "darwin-arm64",
        "macos_x86_64": "darwin-amd64",
    }
    platform_string = platform_mapping[platform.value]
    url = f"https://go.dev/dl/go{version}.{platform_string}.tar.gz"
    package = await Get(
        Digest,
        DownloadFile(
            url,
            FileDigest(
                fingerprint=external_tool.sha256,
                serialized_bytes_length=external_tool.filesize,
            ),
        ),
    )

    extracted_archive = await Get(ExtractedArchive, Digest, package)
    with_prefix = await Get(Digest, AddPrefix(extracted_archive.digest, ".goroot"))

    binary_path = ".goroot/go/bin/go"
    env_result = await Get(  # noqa: PNT30: requires triage
        ProcessResult,
        Process(
            (f"{binary_path}", "env", "-json"),
            description=f"Determine Go SDK metadata for {binary_path}",
            level=LogLevel.DEBUG,
            env={"GOPATH": "/does/not/matter"},
            input_digest=with_prefix,
        ),
    )

    sdk_metadata = json.loads(strip_v2_chroot_path_bytes(env_result.stdout).decode())
    major, minor = version.split(".")[:2]
    version = f"{major}.{minor}"
    print(sdk_metadata)
    print(sdk_metadata["GOROOT"])
    return GoRoot(
        path=sdk_metadata["GOROOT"],
        version=version,
        _raw_metadata=FrozenDict(sdk_metadata),
        digest=extracted_archive.digest,
    )


@rule(desc="Find Go binary", level=LogLevel.DEBUG)
async def setup_goroot(
    golang_subsystem: GolangSubsystem,
    toolchain_subsystem: GoToolchain,
    go_bootstrap: GoBootstrap,
    env_target: EnvironmentTarget,
) -> GoRoot:
    if toolchain_subsystem.enabled:
        print("FOOBAR")
        return await Get(GoRoot, InstallGoToolchainRequest())

    search_paths = go_bootstrap.go_search_paths
    all_go_binary_paths = await Get(
        BinaryPaths,
        BinaryPathRequest(
            search_path=search_paths,
            binary_name="go",
            test=BinaryPathTest(["version"]),
        ),
    )
    if not all_go_binary_paths.paths:
        raise BinaryNotFoundError(
            softwrap(
                f"""
                Cannot find any `go` binaries using the option `[golang].go_search_paths`:
                {list(search_paths)}

                To fix, please install Go (https://golang.org/doc/install) with the version
                {golang_subsystem.minimum_expected_version} or newer (set by
                `[golang].minimum_expected_version`). Then ensure that it is discoverable via
                `[golang].go_search_paths`.
                """
            )
        )

    # `go env GOVERSION` does not work in earlier Go versions (like 1.15), so we must run
    # `go version` and `go env GOROOT` to calculate both the version and GOROOT.
    version_results = await MultiGet(
        Get(
            ProcessResult,
            Process(
                (binary_path.path, "version"),
                description=f"Determine Go version for {binary_path.path}",
                level=LogLevel.DEBUG,
                cache_scope=env_target.executable_search_path_cache_scope(),
            ),
        )
        for binary_path in all_go_binary_paths.paths
    )

    invalid_versions = []
    for binary_path, version_result in zip(all_go_binary_paths.paths, version_results):
        try:
            _raw_version = version_result.stdout.decode("utf-8").split()[
                2
            ]  # e.g. go1.17 or go1.17.1
            _version_components = _raw_version[2:].split(".")  # e.g. [1, 17] or [1, 17, 1]
            version = f"{_version_components[0]}.{_version_components[1]}"
        except IndexError:
            raise AssertionError(
                f"Failed to parse `go version` output for {binary_path}. Please open a bug at "
                f"https://github.com/pantsbuild/pants/issues/new/choose with the below data."
                f"\n\n"
                f"{version_result}"
            )

        if compatible_go_version(
            compiler_version=version, target_version=golang_subsystem.minimum_expected_version
        ):
            env_result = await Get(  # noqa: PNT30: requires triage
                ProcessResult,
                Process(
                    (binary_path.path, "env", "-json"),
                    description=f"Determine Go SDK metadata for {binary_path.path}",
                    level=LogLevel.DEBUG,
                    cache_scope=env_target.executable_search_path_cache_scope(),
                    env={"GOPATH": "/does/not/matter"},
                ),
            )
            sdk_metadata = json.loads(env_result.stdout.decode())
            return GoRoot(
                path=sdk_metadata["GOROOT"], version=version, _raw_metadata=FrozenDict(sdk_metadata)
            )

        logger.debug(
            f"Go binary at {binary_path.path} has version {version}, but this "
            f"repository expects at least {golang_subsystem.minimum_expected_version} "
            "(set by `[golang].expected_minimum_version`). Ignoring."
        )

        invalid_versions.append((binary_path.path, version))

    invalid_versions_str = bullet_list(
        f"{path}: {version}" for path, version in sorted(invalid_versions)
    )
    raise BinaryNotFoundError(
        softwrap(
            f"""
            Cannot find a `go` binary compatible with the minimum version of
            {golang_subsystem.minimum_expected_version} (set by `[golang].minimum_expected_version`).

            Found these `go` binaries, but they had incompatible versions:

            {invalid_versions_str}

            To fix, please install the expected version or newer (https://golang.org/doc/install)
            and ensure that it is discoverable via the option `[golang].go_search_paths`, or change
            `[golang].expected_minimum_version`.
            """
        )
    )


def rules():
    return (
        *collect_rules(),
        *go_bootstrap.rules(),
    )
