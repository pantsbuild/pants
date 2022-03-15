# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from abc import ABCMeta
from dataclasses import dataclass, field
from typing import Any, ClassVar, Generic, Type, TypeVar

import yaml
from typing_extensions import final

from pants.backend.helm.util_rules.yaml_utils import yaml_attr_dict
from pants.core.util_rules.external_tool import (
    DownloadedExternalTool,
    ExternalToolRequest,
    TemplatedExternalTool,
)
from pants.engine.collection import Collection
from pants.engine.fs import Digest, DigestContents, DigestSubset, PathGlobs
from pants.engine.internals.selectors import MultiGet
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.unions import UnionMembership, union
from pants.option.subsystem import Subsystem
from pants.util.frozendict import FrozenDict


class HelmPluginMetadataFileNotFound(Exception):
    def __init__(self, plugin_name: str) -> None:
        super().__init__(f"Helm plugin `{plugin_name}` is missing the `plugin.yaml` metadata file.")


class HelmPluginMissingCommand(ValueError):
    def __init__(self, plugin_name: str) -> None:
        super().__init__(
            f"Helm plugin `{plugin_name}` is missing either `platformCommand` entries or a single `command` entry."
        )


class HelmPluginSubsystem(Subsystem, metaclass=ABCMeta):
    plugin_name: ClassVar[str]


class ExternalHelmPlugin(HelmPluginSubsystem, TemplatedExternalTool, metaclass=ABCMeta):
    pass


@dataclass(frozen=True)
class HelmPluginPlatformCommand:
    os: str
    arch: str
    command: str

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> HelmPluginPlatformCommand:
        return cls(**yaml_attr_dict(d))


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
_GHP = TypeVar("_GHP", bound="HelmPluginBinding")


@union
@dataclass(frozen=True)
class HelmPluginBinding(Generic[_HelmPluginSubsystem], metaclass=ABCMeta):
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
    bindings = union_membership.get(HelmPluginBinding)
    plugins = await MultiGet(
        Get(HelmPlugin, HelmPluginBinding, binding.create()) for binding in bindings
    )
    return HelmPlugins(plugins)


@rule(desc="Downloads a Helm plugin")
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

    return HelmPlugin(metadata=metadata, digest=downloaded_tool.digest)


def rules():
    return collect_rules()
