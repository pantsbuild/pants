# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass

from pants.core.util_rules.system_binaries import (
    BinaryNotFoundError,
    BinaryPathRequest,
    BinaryPaths,
    BinaryPathTest,
)
from pants.engine.environment import Environment, EnvironmentRequest
from pants.engine.process import Process, ProcessCacheScope, ProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.option.option_types import BoolOption, StrListOption, StrOption
from pants.option.subsystem import Subsystem
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.ordered_set import OrderedSet
from pants.util.strutil import bullet_list, softwrap

logger = logging.getLogger(__name__)


class GolangSubsystem(Subsystem):
    options_scope = "golang"
    help = "Options for Golang support."

    _go_search_paths = StrListOption(
        "--go-search-paths",
        default=["<PATH>"],
        help=softwrap(
            """
            A list of paths to search for Go.

            Specify absolute paths to directories with the `go` binary, e.g. `/usr/bin`.
            Earlier entries will be searched first.

            The special string `"<PATH>"` will expand to the contents of the PATH env var.
            """
        ),
    )
    expected_version = StrOption(
        "--expected-version",
        default="1.17",
        help=softwrap(
            """
            The Go version you are using, such as `1.17`.

            Pants will only use Go distributions from `--go-search-paths` that have the
            expected version, and it will error if none are found.

            Do not include the patch version.
            """
        ),
        removal_version="2.14.0.dev0",
        removal_hint=(
            "Use `[golang].minimum_expected_version` instead, which is more flexible. Pants will "
            "now work if your local Go binary is newer than the expected minimum version; e.g. Go "
            "1.18 works with the version set to `1.17`."
        ),
    )
    minimum_version = StrOption(
        "--minimum-expected-version",
        default="1.17",
        help=softwrap(
            """
            The minimum Go version the distribution discovered by Pants must support.

            For example, if you set `'1.17'`, then Pants will look for a Go binary that is 1.17+,
            e.g. 1.17 or 1.18.

            You should still set the Go version for each module in your `go.mod` with the `go`
            directive.

            Do not include the patch version.
            """
        ),
    )
    _subprocess_env_vars = StrListOption(
        "--subprocess-env-vars",
        default=["LANG", "LC_CTYPE", "LC_ALL", "PATH"],
        help=softwrap(
            """
            Environment variables to set when invoking the `go` tool.
            Entries are either strings in the form `ENV_VAR=value` to set an explicit value;
            or just `ENV_VAR` to copy the value from Pants's own environment.
            """
        ),
        advanced=True,
    )

    tailor_go_mod_targets = BoolOption(
        "--tailor-go-mod-targets",
        default=True,
        help=softwrap(
            """
            If true, add a `go_mod` target with the `tailor` goal wherever there is a
            `go.mod` file.
            """
        ),
        advanced=True,
    )
    tailor_package_targets = BoolOption(
        "--tailor-package-targets",
        default=True,
        help=softwrap(
            """
            If true, add a `go_package` target with the `tailor` goal in every directory with a
            `.go` file.
            """
        ),
        advanced=True,
    )
    tailor_binary_targets = BoolOption(
        "--tailor-binary-targets",
        default=True,
        help=softwrap(
            """
            If true, add a `go_binary` target with the `tailor` goal in every directory with a
            `.go` file with `package main`.
            """
        ),
        advanced=True,
    )

    def go_search_paths(self, env: Environment) -> tuple[str, ...]:
        def iter_path_entries():
            for entry in self._go_search_paths:
                if entry == "<PATH>":
                    path = env.get("PATH")
                    if path:
                        yield from path.split(os.pathsep)
                else:
                    yield entry

        return tuple(OrderedSet(iter_path_entries()))

    @property
    def env_vars_to_pass_to_subprocesses(self) -> tuple[str, ...]:
        return tuple(sorted(set(self._subprocess_env_vars)))


def compatible_go_version(*, compiler_version: str, target_version: str) -> bool:
    """Can the Go compiler handle the target version?

    Inspired by
    https://github.com/golang/go/blob/30501bbef9fcfc9d53e611aaec4d20bb3cdb8ada/src/cmd/go/internal/work/exec.go#L429-L445.

    Input expected in the form `1.17`.
    """
    if target_version == "1.0":
        return True

    def parse(v: str) -> tuple[int, int]:
        major, minor = v.split(".", maxsplit=1)
        return int(major), int(minor)

    return parse(target_version) <= parse(compiler_version)


@dataclass(frozen=True)
class GoRoot:
    """Path to the Go installation (the `GOROOT`)."""

    path: str
    version: str

    _raw_metadata: FrozenDict[str, str]

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


@rule(desc="Find Go binary", level=LogLevel.DEBUG)
async def setup_goroot(golang_subsystem: GolangSubsystem) -> GoRoot:
    env = await Get(Environment, EnvironmentRequest(["PATH"]))
    search_paths = golang_subsystem.go_search_paths(env)
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
            "Cannot find any `go` binaries using the option "
            f"`[golang].go_search_paths`: {list(search_paths)}\n\n"
            "To fix, please install Go (https://golang.org/doc/install) with the version "
            f"{golang_subsystem.expected_version} (set by `[golang].expected_version`) and ensure "
            "that it is discoverable via `[golang].go_search_paths`."
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
                cache_scope=ProcessCacheScope.PER_RESTART_SUCCESSFUL,
            ),
        )
        for binary_path in all_go_binary_paths.paths
    )

    using_exact_match = not golang_subsystem.options.is_default("expected_version")

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

        is_match = (
            golang_subsystem.expected_version == version
            if using_exact_match
            else compatible_go_version(
                compiler_version=version, target_version=golang_subsystem.minimum_version
            )
        )
        if is_match:
            env_result = await Get(
                ProcessResult,
                Process(
                    (binary_path.path, "env", "-json"),
                    description=f"Determine Go SDK metadata for {binary_path.path}",
                    level=LogLevel.DEBUG,
                    cache_scope=ProcessCacheScope.PER_RESTART_SUCCESSFUL,
                    env={"GOPATH": "/does/not/matter"},
                ),
            )
            sdk_metadata = json.loads(env_result.stdout.decode())
            return GoRoot(
                path=sdk_metadata["GOROOT"], version=version, _raw_metadata=FrozenDict(sdk_metadata)
            )

        if using_exact_match:
            logger.debug(
                f"Go binary at {binary_path.path} has version {version}, but this "
                f"project is using {golang_subsystem.expected_version} "
                "(set by `[golang].expected_version`). Ignoring."
            )
        else:
            logger.debug(
                f"Go binary at {binary_path.path} has version {version}, but this "
                f"repository expects at least {golang_subsystem.expected_version} "
                "(set by `[golang].expected_minimum_version`). Ignoring."
            )

        invalid_versions.append((binary_path.path, version))

    invalid_versions_str = bullet_list(
        f"{path}: {version}" for path, version in sorted(invalid_versions)
    )
    if using_exact_match:
        err = softwrap(
            f"""
            Cannot find a `go` binary with the expected version of
            {golang_subsystem.expected_version} (set by `[golang].expected_version`).

            Found these `go` binaries, but they had different versions:

            {invalid_versions_str}

            To fix, please install the expected version (https://golang.org/doc/install)
            and ensure that it is discoverable via the option `[golang].go_search_paths`, or change
            `[golang].expected_version`.
            """
        )
    else:
        err = softwrap(
            f"""
            Cannot find a `go` binary compatible with the minimum version of
            {golang_subsystem.minimum_version} (set by `[golang].minimum_expected_version`).

            Found these `go` binaries, but they had incompatible versions:

            {invalid_versions_str}

            To fix, please install the expected version or newer (https://golang.org/doc/install)
            and ensure that it is discoverable via the option `[golang].go_search_paths`, or change
            `[golang].expected_minimum_version`.
            """
        )
    raise BinaryNotFoundError(err)


def rules():
    return collect_rules()
