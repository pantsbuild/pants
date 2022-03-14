# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from abc import ABCMeta
from dataclasses import dataclass, field
from typing import Any, ClassVar, Generic, Iterable, Type, TypeVar, final

import yaml

from pants.backend.helm.util_rules.yaml_utils import yaml_attr_dict
from pants.core.util_rules.external_tool import (
    DownloadedExternalTool,
    ExternalToolRequest,
    TemplatedExternalTool,
)
from pants.engine.collection import Collection
from pants.engine.fs import Digest, DigestContents, DigestSubset, PathGlobs
from pants.engine.internals.selectors import MultiGet
from pants.engine.platform import Platform
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.unions import UnionMembership, union
from pants.util.frozendict import FrozenDict
from pants.util.strutil import bullet_list


class HelmPluginMetadataFileNotFound(Exception):
    def __init__(self, plugin_name: str) -> None:
        super().__init__(f"Helm plugin `{plugin_name}` is missing the `plugin.yaml` metadata file.")


class HelmPluginMissingCommand(ValueError):
    def __init__(self, plugin_name: str) -> None:
        super().__init__(
            f"Helm plugin `{plugin_name}` is missing either `platformCommand` entries or a single `command` entry."
        )


class HelmPluginPlatformNotSupported(Exception):
    def __init__(
        self, plugin_name: str, current_platf: Platform, supported_platfs: Iterable[str]
    ) -> None:
        super().__init__(
            f"Helm plugin `{plugin_name}` can not be used under current platform "
            f"`{current_platf.value}`. Supported platforms are:\n{bullet_list(supported_platfs)}"
        )


@dataclass(frozen=True)
class HelmPluginPlatform:
    os: str
    arch: str


class HelmPluginSubsystem(TemplatedExternalTool, metaclass=ABCMeta):
    plugin_name: ClassVar[str]

    def map_platform(self, platform: Platform) -> HelmPluginPlatform:
        pass


@dataclass(frozen=True)
class HelmPluginPlatformCommand:
    os: str
    arch: str
    command: str

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> HelmPluginPlatformCommand:
        return cls(**yaml_attr_dict(d))

    def supports_platform(self, plugin_platform: HelmPluginPlatform) -> bool:
        return self.os == plugin_platform and self.arch == plugin_platform.arch

    @property
    def platform(self) -> HelmPluginPlatform:
        return HelmPluginPlatform(os=self.os, arch=self.arch)


@dataclass(frozen=True)
class HelmPluginMetadata:
    name: str
    version: str
    usage: str | None = None
    description: str | None = None
    ignore_flags: bool | None = None
    command: str | None = None
    platform_command: tuple[HelmPluginPlatformCommand, ...] = field(default_factory=tuple)
    hooks: FrozenDict[str, str] = field(default_factory=FrozenDict)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> HelmPluginMetadata:
        platform_command = [
            HelmPluginPlatformCommand.from_dict(d) for d in d.pop("platformCommand", [])
        ]
        hooks = d.pop("hooks", {})

        attrs = yaml_attr_dict(d)
        return cls(platform_command=tuple(platform_command), hooks=FrozenDict(hooks), **attrs)

    @classmethod
    def from_bytes(cls, content: bytes) -> HelmPluginMetadata:
        return HelmPluginMetadata.from_dict(yaml.safe_load(content))


_HelmPluginSubsystem = TypeVar("_HelmPluginSubsystem", bound=HelmPluginSubsystem)
_GHP = TypeVar("_GHP", bound="GlobalHelmPlugin")


@union
@dataclass(frozen=True)
class GlobalHelmPlugin(Generic[_HelmPluginSubsystem], metaclass=ABCMeta):
    plugin_subsystem_cls: ClassVar[Type[HelmPluginSubsystem]]

    name: str

    @final
    @classmethod
    def create(cls: Type[_GHP]) -> _GHP:
        return cls(name=cls.plugin_subsystem_cls.plugin_name)


@dataclass(frozen=True)
class HelmPluginRequest:
    plugin_name: str
    tool_request: ExternalToolRequest


@dataclass(frozen=True)
class HelmPlugin:
    metadata: HelmPluginMetadata
    digest: Digest

    @property
    def name(self) -> str:
        return self.metadata.name


class HelmPlugins(Collection[HelmPlugin]):
    pass


@rule
async def download_all_global_helm_plugins(union_membership: UnionMembership) -> HelmPlugins:
    all_plugin_settings = union_membership.get(GlobalHelmPlugin)
    requests = await MultiGet(
        Get(HelmPluginRequest, GlobalHelmPlugin, plugin_settings.create())
        for plugin_settings in all_plugin_settings
    )
    plugins = await MultiGet(Get(HelmPlugin, HelmPluginRequest, request) for request in requests)
    return HelmPlugins(plugins)


@rule
async def download_helm_plugin(request: HelmPluginRequest) -> HelmPlugin:
    downloaded_tool = await Get(DownloadedExternalTool, ExternalToolRequest, request.tool_request)

    metadata_file = await Get(
        Digest, DigestSubset(downloaded_tool.digest, PathGlobs(["plugin.yaml"]))
    )
    metadata_content = await Get(DigestContents, Digest, metadata_file)
    if len(metadata_content) == 0:
        raise HelmPluginMetadataFileNotFound(request.plugin_name)

    metadata = HelmPluginMetadata.from_bytes(metadata_content[0].content)
    if not metadata.command and not metadata.platform_command:
        raise HelmPluginMissingCommand(request.plugin_name)

    # TODO
    # if metadata.platform_command:
    #     current_helm_platf = request.subsystem.map_platform(Platform.current)
    #     supported_cmds = [
    #         cmd for cmd in metadata.platform_command if cmd.supports_platform(current_helm_platf)
    #     ]
    #     if len(supported_cmds) == 0:
    #         raise HelmPluginPlatformNotSupported(
    #             request.plugin_name,
    #             Platform.current,
    #             [f"{cmd.platform}" for cmd in metadata.platform_command],
    #         )

    return HelmPlugin(metadata=metadata, digest=downloaded_tool.digest)


def rules():
    return collect_rules()
