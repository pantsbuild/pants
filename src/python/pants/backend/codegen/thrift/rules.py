# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import logging
from dataclasses import dataclass

from pants.backend.codegen.thrift.subsystem import ThriftSubsystem
from pants.engine.environment import Environment, EnvironmentRequest
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.process import (
    BinaryNotFoundError,
    BinaryPathRequest,
    BinaryPaths,
    BinaryPathTest,
    Process,
    ProcessCacheScope,
    ProcessResult,
)
from pants.engine.rules import collect_rules, rule
from pants.util.logging import LogLevel
from pants.util.strutil import bullet_list

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ThriftSetup:
    path: str


@rule
async def setup_thrift_tool(thrift_subsystem: ThriftSubsystem) -> ThriftSetup:
    env = await Get(Environment, EnvironmentRequest(["PATH"]))
    search_paths = thrift_subsystem.thrift_search_paths(env)
    all_thrift_binary_paths = await Get(
        BinaryPaths,
        BinaryPathRequest(
            search_path=search_paths,
            binary_name="thrift",
            test=BinaryPathTest(["-version"]),
        ),
    )
    if not all_thrift_binary_paths.paths:
        raise BinaryNotFoundError(
            "Cannot find any `thrift` binaries using the option "
            f"`[thrift].thrift_search_paths`: {list(search_paths)}\n\n"
            "To fix, please install Thrift (https://thrift.apache.org/) with the version "
            f"{thrift_subsystem.expected_version} (set by `[thrift].expected_version`) and ensure "
            "that it is discoverable via `[thrift].thrift_search_paths`."
        )

    version_results = await MultiGet(
        Get(
            ProcessResult,
            Process(
                (binary_path.path, "-version"),
                description=f"Determine Thrift version for {binary_path.path}",
                level=LogLevel.DEBUG,
                cache_scope=ProcessCacheScope.PER_RESTART_SUCCESSFUL,
            ),
        )
        for binary_path in all_thrift_binary_paths.paths
    )

    invalid_versions = []
    for binary_path, version_result in zip(all_thrift_binary_paths.paths, version_results):
        try:
            _raw_version = version_result.stdout.decode("utf-8").split()[2]
            _version_components = _raw_version[2:].split(".")  # e.g. [1, 17] or [1, 17, 1]
            version = f"{_version_components[0]}.{_version_components[1]}"
        except IndexError:
            raise AssertionError(
                f"Failed to parse `thrift -version` output for {binary_path}. Please open a bug at "
                f"https://github.com/pantsbuild/pants/issues/new/choose with the below data:"
                f"\n\n"
                f"{version_result}"
            )

        if version == thrift_subsystem.expected_version:
            return ThriftSetup(binary_path.path)

        logger.debug(
            f"The Thrift binary at {binary_path.path} has version {version}, but this "
            f"project is using {thrift_subsystem.expected_version} "
            "(set by `[thrift].expected_version`). Ignoring."
        )
        invalid_versions.append((binary_path.path, version))

    invalid_versions_str = bullet_list(
        f"{path}: {version}" for path, version in sorted(invalid_versions)
    )
    raise BinaryNotFoundError(
        "Cannot find a `thrift` binary with the expected version of "
        f"{thrift_subsystem.expected_version} (set by `[thrift].expected_version`).\n\n"
        f"Found these `thrift` binaries, but they had different versions:\n\n"
        f"{invalid_versions_str}\n\n"
        "To fix, please install the expected version (https://thrift.apache.org/) and ensure "
        "that it is discoverable via the option `[thrift].thrift_search_paths`, or change "
        "`[thrift].expected_version`."
    )


def rules():
    return collect_rules()
