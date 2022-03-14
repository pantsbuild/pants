# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from abc import ABCMeta
from dataclasses import dataclass, field
from typing import Any, ClassVar, Iterable

import yaml

from pants.backend.helm.util_rules.yaml_utils import yaml_attr_dict
from pants.core.util_rules.external_tool import (
    DownloadedExternalTool,
    ExternalToolRequest,
    TemplatedExternalTool,
)
from pants.engine.fs import Digest, DigestContents, DigestSubset, PathGlobs
from pants.engine.platform import Platform
from pants.engine.rules import Get, collect_rules, rule
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
class DownloadHelmPlugin:
    subsystem: HelmPluginSubsystem


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

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> HelmPluginMetadata:
        platform_command = [
            HelmPluginPlatformCommand.from_dict(d) for d in d.pop("platformCommand", [])
        ]

        attrs = yaml_attr_dict(d)
        return cls(platform_command=tuple(platform_command), **attrs)

    @classmethod
    def from_bytes(cls, content: bytes) -> HelmPluginMetadata:
        return HelmPluginMetadata.from_dict(yaml.safe_load(content))


@dataclass(frozen=True)
class HelmPlugin:
    metadata: HelmPluginMetadata
    digest: Digest


@rule
async def download_helm_plugin(request: DownloadHelmPlugin) -> HelmPlugin:
    downloaded_tool = await Get(
        DownloadedExternalTool, ExternalToolRequest, request.subsystem.get_request(Platform.current)
    )

    metadata_file = await Get(
        Digest, DigestSubset(downloaded_tool.digest, PathGlobs(["**/plugin.yaml"]))
    )
    metadata_content = await Get(DigestContents, Digest, metadata_file)
    if len(metadata_content) == 0:
        raise HelmPluginMetadataFileNotFound(request.subsystem.plugin_name)

    metadata = HelmPluginMetadata.from_bytes(metadata_content[0].content)
    if not metadata.command and not metadata.platform_command:
        raise HelmPluginMissingCommand(request.subsystem.plugin_name)

    if metadata.platform_command:
        current_helm_platf = request.subsystem.map_platform(Platform.current)
        supported_cmds = [
            cmd for cmd in metadata.platform_command if cmd.supports_platform(current_helm_platf)
        ]
        if len(supported_cmds) == 0:
            raise HelmPluginPlatformNotSupported(
                request.subsystem.plugin_name,
                Platform.current,
                [f"{cmd.platform}" for cmd in metadata.platform_command],
            )

    return HelmPlugin(metadata=metadata, digest=downloaded_tool.digest)


def rules():
    return collect_rules()
