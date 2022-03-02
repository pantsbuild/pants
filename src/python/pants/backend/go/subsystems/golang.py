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
from pants.option.option_types import StrListOption, StrOption
from pants.option.subsystem import Subsystem
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.ordered_set import OrderedSet
from pants.util.strutil import bullet_list

logger = logging.getLogger(__name__)


class GolangSubsystem(Subsystem):
    options_scope = "golang"
    help = "Options for Golang support."

    _go_search_paths = StrListOption(
        "--go-search-paths",
        default=["<PATH>"],
        help=(
            "A list of paths to search for Go.\n\n"
            "Specify absolute paths to directories with the `go` binary, e.g. `/usr/bin`. "
            "Earlier entries will be searched first.\n\n"
            "The special string '<PATH>' will expand to the contents of the PATH env var."
        ),
    )
    # TODO(#13005): Support multiple Go versions in a project?
    expected_version = StrOption(
        "--expected-version",
        default="1.17",
        help=(
            "The Go version you are using, such as `1.17`.\n\n"
            "Pants will only use Go distributions from `--go-search-paths` that have the "
            "expected version, and it will error if none are found.\n\n"
            "Do not include the patch version."
        ),
    )
    _subprocess_env_vars = StrListOption(
        "--subprocess-env-vars",
        default=["LANG", "LC_CTYPE", "LC_ALL", "PATH"],
        help=(
            "Environment variables to set when invoking the `go` tool. "
            "Entries are either strings in the form `ENV_VAR=value` to set an explicit value; "
            "or just `ENV_VAR` to copy the value from Pants's own environment."
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


@dataclass(frozen=True)
class GoRoot:
    """Path to the Go installation (the `GOROOT`)."""

    path: str
    version: str

    _raw_metadata: FrozenDict[str, str]

    def is_compatible_version(self, version: str) -> bool:
        """Can this Go compiler handle the target version?

        Inspired by
        https://github.com/golang/go/blob/30501bbef9fcfc9d53e611aaec4d20bb3cdb8ada/src/cmd/go/internal/work/exec.go#L429-L445.

        Input expected in the form `1.17`.
        """
        if version == "1.0":
            return True

        def parse(v: str) -> tuple[int, int]:
            major, minor = v.split(".", maxsplit=1)
            return int(major), int(minor)

        return parse(version) <= parse(self.version)

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

        if version == golang_subsystem.expected_version:
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

        logger.debug(
            f"Go binary at {binary_path.path} has version {version}, but this "
            f"project is using {golang_subsystem.expected_version} "
            "(set by `[golang].expected_version`). Ignoring."
        )
        invalid_versions.append((binary_path.path, version))

    invalid_versions_str = bullet_list(
        f"{path}: {version}" for path, version in sorted(invalid_versions)
    )
    raise BinaryNotFoundError(
        "Cannot find a `go` binary with the expected version of "
        f"{golang_subsystem.expected_version} (set by `[golang].expected_version`).\n\n"
        f"Found these `go` binaries, but they had different versions:\n\n"
        f"{invalid_versions_str}\n\n"
        "To fix, please install the expected version (https://golang.org/doc/install) and ensure "
        "that it is discoverable via the option `[golang].go_search_paths`, or change "
        "`[golang].expected_version`."
    )


def rules():
    return collect_rules()
