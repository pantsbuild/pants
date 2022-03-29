# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from abc import ABCMeta
from dataclasses import dataclass, field
from typing import Any, ClassVar, Generic, Type, TypeVar

import yaml
from typing_extensions import final

from pants.backend.helm.util_rules.yaml_utils import snake_case_attr_dict
from pants.base.glob_match_error_behavior import GlobMatchErrorBehavior
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
from pants.option.subsystem import Subsystem
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.strutil import bullet_list, pluralize

logger = logging.getLogger(__name__)


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
        return cls(**snake_case_attr_dict(d))


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

        attrs = snake_case_attr_dict(d)
        return cls(platform_command=tuple(platform_command), hooks=FrozenDict(hooks), **attrs)

    @classmethod
    def from_bytes(cls, content: bytes) -> HelmPluginMetadata:
        return HelmPluginMetadata.from_dict(yaml.safe_load(content))


_ExternalHelmPlugin = TypeVar("_ExternalHelmPlugin", bound=ExternalHelmPlugin)
_GHP = TypeVar("_GHP", bound="ExternalHelmPluginBinding")


@union
@dataclass(frozen=True)
class ExternalHelmPluginBinding(Generic[_ExternalHelmPlugin], metaclass=ABCMeta):
    plugin_subsystem_cls: ClassVar[Type[ExternalHelmPlugin]]

    name: str

    @final
    @classmethod
    def create(cls: Type[_GHP]) -> _GHP:
        return cls(name=cls.plugin_subsystem_cls.plugin_name)


@dataclass(frozen=True)
class ExternalHelmPluginRequest:
    plugin_name: str
    tool_request: ExternalToolRequest

    @classmethod
    def from_subsystem(cls, subsystem: ExternalHelmPlugin) -> ExternalHelmPluginRequest:
        return cls(
            plugin_name=subsystem.plugin_name, tool_request=subsystem.get_request(Platform.current)
        )


@dataclass(frozen=True)
class HelmPlugin:
    metadata: HelmPluginMetadata
    digest: Digest

    @property
    def name(self) -> str:
        return self.metadata.name

    @property
    def version(self) -> str:
        return self.metadata.version


class HelmPlugins(Collection[HelmPlugin]):
    pass


@rule
async def all_helm_plugins(union_membership: UnionMembership) -> HelmPlugins:
    bindings = union_membership.get(ExternalHelmPluginBinding)
    external_plugins = await MultiGet(
        Get(HelmPlugin, ExternalHelmPluginBinding, binding.create()) for binding in bindings
    )
    if logger.isEnabledFor(LogLevel.DEBUG.level):
        plugins_desc = [f"{p.name}, version: {p.version}" for p in external_plugins]
        logger.debug(
            f"Downloaded {pluralize(len(external_plugins), 'external Helm plugin')}:\n{bullet_list(plugins_desc)}"
        )
    return HelmPlugins(external_plugins)


@rule(desc="Download an external Helm plugin", level=LogLevel.DEBUG)
async def download_external_helm_plugin(request: ExternalHelmPluginRequest) -> HelmPlugin:
    downloaded_tool = await Get(DownloadedExternalTool, ExternalToolRequest, request.tool_request)

    metadata_file = await Get(
        Digest,
        DigestSubset(
            downloaded_tool.digest,
            PathGlobs(
                ["plugin.yaml"],
                glob_match_error_behavior=GlobMatchErrorBehavior.error,
                description_of_origin=f"The Helm plugin `{request.plugin_name}`",
            ),
        ),
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
