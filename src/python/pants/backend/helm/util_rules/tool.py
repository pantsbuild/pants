# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import dataclasses
import os
from dataclasses import dataclass
from typing import Iterable, Mapping

from pants.backend.helm.subsystems.helm import HelmSubsystem
from pants.backend.helm.util_rules.plugins import HelmPlugins
from pants.backend.helm.util_rules.plugins import rules as plugins_rules
from pants.core.util_rules.external_tool import DownloadedExternalTool, ExternalToolRequest
from pants.engine.environment import Environment, EnvironmentRequest
from pants.engine.fs import CreateDigest, Digest, DigestSubset, Directory, PathGlobs, RemovePrefix
from pants.engine.internals.native_engine import AddPrefix, MergeDigests
from pants.engine.platform import Platform
from pants.engine.process import Process, ProcessCacheScope
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.meta import frozen_after_init

_HELM_CACHE_NAME = "helm"
_HELM_CACHE_DIR = "__cache"
_HELM_CONFIG_DIR = "__config"
_HELM_DATA_DIR = "__data"


@frozen_after_init
@dataclass(unsafe_hash=True)
class HelmBinary:
    path: str

    env: FrozenDict[str, str]
    immutable_input_digests: FrozenDict[str, Digest]

    def __init__(
        self,
        path: str,
        *,
        helm_env: Mapping[str, str],
        local_env: Mapping[str, str],
        immutable_input_digests: Mapping[str, Digest],
    ) -> None:
        self.path = path
        self.immutable_input_digests = FrozenDict(immutable_input_digests)
        self.env = FrozenDict({**helm_env, **local_env})

    @property
    def config_digest(self) -> Digest:
        return self.immutable_input_digests[_HELM_CONFIG_DIR]

    @property
    def data_digest(self) -> Digest:
        return self.immutable_input_digests[_HELM_DATA_DIR]

    @property
    def append_only_caches(self) -> dict[str, str]:
        return {_HELM_CACHE_NAME: _HELM_CACHE_DIR}


@frozen_after_init
@dataclass(unsafe_hash=True)
class HelmProcess:
    argv: tuple[str, ...]
    input_digest: Digest
    description: str = dataclasses.field(compare=False)
    level: LogLevel
    extra_env: FrozenDict[str, str]
    extra_immutable_input_digests: FrozenDict[str, Digest]
    cache_scope: ProcessCacheScope | None
    output_directories: tuple[str, ...]
    output_files: tuple[str, ...]

    def __init__(
        self,
        argv: Iterable[str],
        *,
        input_digest: Digest,
        description: str,
        level: LogLevel = LogLevel.INFO,
        output_directories: Iterable[str] | None = None,
        output_files: Iterable[str] | None = None,
        extra_env: Mapping[str, str] | None = None,
        extra_immutable_input_digests: Mapping[str, Digest] | None = None,
        cache_scope: ProcessCacheScope | None = None,
    ):
        self.argv = tuple(argv)
        self.input_digest = input_digest
        self.description = description
        self.level = level
        self.output_directories = tuple(output_directories or ())
        self.output_files = tuple(output_files or ())
        self.extra_env = FrozenDict(extra_env or {})
        self.extra_immutable_input_digests = FrozenDict(extra_immutable_input_digests or {})
        self.cache_scope = cache_scope


@rule(desc="Download and configure Helm", level=LogLevel.DEBUG)
async def setup_helm(helm_subsytem: HelmSubsystem, global_plugins: HelmPlugins) -> HelmBinary:
    downloaded_binary, empty_dirs_digest = await MultiGet(
        Get(
            DownloadedExternalTool, ExternalToolRequest, helm_subsytem.get_request(Platform.current)
        ),
        Get(
            Digest,
            CreateDigest(
                [
                    Directory(_HELM_CONFIG_DIR),
                    Directory(_HELM_DATA_DIR),
                ]
            ),
        ),
    )

    tool_relpath = "__helm"
    immutable_input_digests = {tool_relpath: downloaded_binary.digest}

    helm_path = os.path.join(tool_relpath, downloaded_binary.exe)
    helm_env = {
        "HELM_CACHE_HOME": _HELM_CACHE_DIR,
        "HELM_CONFIG_HOME": _HELM_CONFIG_DIR,
        "HELM_DATA_HOME": _HELM_DATA_DIR,
    }

    # Create a digest that will get mutated during the setup process
    mutable_input_digest = empty_dirs_digest

    # Install all global Helm plugins
    if global_plugins:
        prefixed_plugins_digests = await MultiGet(
            Get(
                Digest,
                AddPrefix(plugin.digest, os.path.join(_HELM_DATA_DIR, "plugins", plugin.name)),
            )
            for plugin in global_plugins
        )
        mutable_input_digest = await Get(
            Digest, MergeDigests([mutable_input_digest, *prefixed_plugins_digests])
        )

    updated_config_digest, updated_data_digest = await MultiGet(
        Get(
            Digest,
            DigestSubset(mutable_input_digest, PathGlobs([os.path.join(_HELM_CONFIG_DIR, "**")])),
        ),
        Get(
            Digest,
            DigestSubset(mutable_input_digest, PathGlobs([os.path.join(_HELM_DATA_DIR, "**")])),
        ),
    )
    config_subset_digest, data_subset_digest = await MultiGet(
        Get(Digest, RemovePrefix(updated_config_digest, _HELM_CONFIG_DIR)),
        Get(Digest, RemovePrefix(updated_data_digest, _HELM_DATA_DIR)),
    )

    setup_immutable_digests = {
        **immutable_input_digests,
        _HELM_CONFIG_DIR: config_subset_digest,
        _HELM_DATA_DIR: data_subset_digest,
    }

    local_env = await Get(Environment, EnvironmentRequest(["HOME", "PATH"]))
    return HelmBinary(
        path=helm_path,
        helm_env=helm_env,
        local_env=local_env,
        immutable_input_digests=setup_immutable_digests,
    )


@rule
def helm_process(request: HelmProcess, helm_binary: HelmBinary) -> Process:
    env = {**helm_binary.env, **request.extra_env}

    immutable_input_digests = {
        **helm_binary.immutable_input_digests,
        **request.extra_immutable_input_digests,
    }

    return Process(
        [helm_binary.path, *request.argv],
        input_digest=request.input_digest,
        immutable_input_digests=immutable_input_digests,
        env=env,
        description=request.description,
        level=request.level,
        append_only_caches=helm_binary.append_only_caches,
        output_directories=request.output_directories,
        output_files=request.output_files,
        cache_scope=request.cache_scope or ProcessCacheScope.SUCCESSFUL,
    )


def rules():
    return [*collect_rules(), *plugins_rules()]
