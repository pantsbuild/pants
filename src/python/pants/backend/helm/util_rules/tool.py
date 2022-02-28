# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

from pants.backend.helm.subsystems.helm import HelmSubsystem
from pants.core.util_rules.external_tool import DownloadedExternalTool, ExternalToolRequest
from pants.engine.environment import Environment, EnvironmentRequest
from pants.engine.fs import EMPTY_DIGEST, CreateDigest, Digest, Directory, RemovePrefix
from pants.engine.platform import Platform
from pants.engine.process import Process, ProcessCacheScope
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.meta import frozen_after_init


@frozen_after_init
@dataclass(unsafe_hash=True)
class HelmBinary:
    path: str

    env: FrozenDict[str, str]

    cache_dir: str
    config_dir: str
    data_dir: str

    _setup_digests: FrozenDict[str, Digest]

    def __init__(
        self,
        path: str,
        *,
        cache_dir: str,
        config_dir: str,
        data_dir: str,
        local_env: Mapping[str, str],
        setup_digests: Mapping[str, Digest],
    ) -> None:
        self.path = path
        self.cache_dir = cache_dir
        self.config_dir = config_dir
        self.data_dir = data_dir
        self._setup_digests = FrozenDict(setup_digests)
        self.env = FrozenDict(
            {**local_env, **_build_helm_env(self.cache_dir, self.config_dir, self.data_dir)}
        )

    def _cmd(
        self,
        args: Iterable[str],
        *,
        description: str,
        level: LogLevel = LogLevel.DEBUG,
        input_digest: Digest = EMPTY_DIGEST,
        immutable_input_digests: Mapping[str, Digest] = {},
        output_directories: Iterable[str] = (),
        cache_scope: ProcessCacheScope = ProcessCacheScope.SUCCESSFUL,
    ) -> Process:
        return Process(
            [self.path, *args],
            env=self.env,
            description=description,
            level=level,
            input_digest=input_digest,
            output_directories=output_directories,
            immutable_input_digests={**self._setup_digests, **immutable_input_digests},
            cache_scope=cache_scope,
        )


def _build_helm_env(cache_dir: str, config_dir: str, data_dir: str) -> FrozenDict[str, str]:
    return FrozenDict(
        {
            "HELM_CACHE_HOME": cache_dir,
            "HELM_CONFIG_HOME": config_dir,
            "HELM_DATA_HOME": data_dir,
        }
    )


@rule(desc="Setup Helm binary", level=LogLevel.DEBUG)
async def setup_helm_binary(helm_subsytem: HelmSubsystem) -> HelmBinary:
    cache_dir = "__cache"
    config_dir = "__config"
    data_dir = "__data"

    downloaded_binary, cache_digest, config_digest, data_digest = await MultiGet(
        Get(
            DownloadedExternalTool, ExternalToolRequest, helm_subsytem.get_request(Platform.current)
        ),
        Get(Digest, CreateDigest([Directory(cache_dir)])),
        Get(Digest, CreateDigest([Directory(config_dir)])),
        Get(Digest, CreateDigest([Directory(data_dir)])),
    )

    tool_relpath = "__helm"
    immutable_input_digests = {tool_relpath: downloaded_binary.digest}
    helm_path = f"{tool_relpath}/{downloaded_binary.exe}"

    # TODO Install Global Helm plugins
    # TODO Configure Helm classic repositories

    cache_subset_digest, config_subset_digest, data_subset_digest = await MultiGet(
        Get(Digest, RemovePrefix(cache_digest, cache_dir)),
        Get(Digest, RemovePrefix(config_digest, config_dir)),
        Get(Digest, RemovePrefix(data_digest, data_dir)),
    )

    setup_immutable_digests = {
        **immutable_input_digests,
        cache_dir: cache_subset_digest,
        config_dir: config_subset_digest,
        data_dir: data_subset_digest,
    }

    local_env = await Get(Environment, EnvironmentRequest(["HOME", "PATH"]))
    return HelmBinary(
        path=helm_path,
        cache_dir=cache_dir,
        config_dir=config_dir,
        data_dir=data_dir,
        local_env=local_env,
        setup_digests=setup_immutable_digests,
    )


def rules():
    return collect_rules()
