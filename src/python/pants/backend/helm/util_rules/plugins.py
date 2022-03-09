from __future__ import annotations

from abc import ABCMeta
from typing import ClassVar, Type, TypeVar
from dataclasses import dataclass
from typing_extensions import final
from pants.engine.unions import UnionMembership, union
from pants.engine.fs import Digest
from pants.core.util_rules.external_tool import (
    DownloadedExternalTool,
    ExternalToolRequest,
    TemplatedExternalTool,
)
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.platform import Platform

class HelmPluginSubsystem(TemplatedExternalTool, metaclass=ABCMeta):
    plugin_name: ClassVar[str]


@dataclass(frozen=True)
class DownloadHelmPlugin:
    subsystem: HelmPluginSubsystem


@dataclass(frozen=True)
class HelmPlugin:
    name: str
    version: str
    digest: Digest

    @classmethod
    def from_downloaded_external_tool(
        cls, plugin: HelmPluginSubsystem, tool: DownloadedExternalTool
    ) -> HelmPlugin:
        return cls(name=plugin.plugin_name, version=plugin.version, digest=tool.digest)

@rule
async def download_helm_plugin(request: DownloadHelmPlugin) -> HelmPlugin:
  downloaded_tool = await Get(DownloadedExternalTool, ExternalToolRequest, request.subsystem.get_request(Platform.current))
  return HelmPlugin.from_downloaded_external_tool(request.subsystem, downloaded_tool)

def rules():
  return collect_rules()