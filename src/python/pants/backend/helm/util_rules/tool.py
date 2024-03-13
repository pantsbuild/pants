# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import dataclasses
import logging
import os
from abc import ABCMeta
from dataclasses import dataclass
from typing import Any, ClassVar, Generic, Iterable, Mapping, Type, TypeVar

import yaml
from typing_extensions import final

from pants.backend.helm.subsystems.helm import HelmSubsystem
from pants.backend.helm.utils.yaml import snake_case_attr_dict
from pants.base.glob_match_error_behavior import GlobMatchErrorBehavior
from pants.core.util_rules import external_tool
from pants.core.util_rules.external_tool import (
    DownloadedExternalTool,
    ExternalToolRequest,
    TemplatedExternalTool,
)
from pants.engine import process
from pants.engine.collection import Collection
from pants.engine.engine_aware import EngineAwareParameter, EngineAwareReturnType
from pants.engine.env_vars import EnvironmentVars, EnvironmentVarsRequest
from pants.engine.environment import EnvironmentName
from pants.engine.fs import (
    EMPTY_DIGEST,
    AddPrefix,
    CreateDigest,
    Digest,
    DigestContents,
    DigestSubset,
    Directory,
    FileDigest,
    MergeDigests,
    PathGlobs,
    RemovePrefix,
    Snapshot,
)
from pants.engine.platform import Platform
from pants.engine.process import Process, ProcessCacheScope
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.unions import UnionMembership, union
from pants.option.subsystem import Subsystem
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.strutil import bullet_list, pluralize

logger = logging.getLogger(__name__)

_HELM_CACHE_NAME = "helm"
_HELM_CACHE_DIR = "__cache"
_HELM_CONFIG_DIR = "__config"
_HELM_DATA_DIR = "__data"

# ---------------------------------------------
# Helm Plugins Support
# ---------------------------------------------


class HelmPluginMetadataFileNotFound(Exception):
    def __init__(self, plugin_name: str) -> None:
        super().__init__(f"Helm plugin `{plugin_name}` is missing the `plugin.yaml` metadata file.")


class HelmPluginMissingCommand(ValueError):
    def __init__(self, plugin_name: str) -> None:
        super().__init__(
            f"Helm plugin `{plugin_name}` is missing either `platformCommand` entries or a single `command` entry."
        )


class HelmPluginSubsystem(Subsystem, metaclass=ABCMeta):
    """Base class for any kind of Helm plugin."""

    plugin_name: ClassVar[str]


class ExternalHelmPlugin(HelmPluginSubsystem, TemplatedExternalTool, metaclass=ABCMeta):
    """Represents the subsystem for a Helm plugin that needs to be downloaded from an external
    source.

    For declaring an External Helm plugin, extend this class providing a value of the
    `plugin_name` class attribute and implement the rest of it like you would do for
    any other `TemplatedExternalTool`.

    This class is meant to be used in combination with `ExternalHelmPluginBinding`, as
    in the following example:

    class MyHelmPluginSubsystem(ExternalHelmPlugin):
        plugin_name = "myplugin"
        options_scope = "my_plugin"
        help = "..."

        ...


    class MyPluginBinding(ExternalHelmPluginBinding[MyPluginSubsystem]):
        plugin_subsystem_cls = MyHelmPluginSubsystem

    With that class structure, then define a `UnionRule` so Pants can find this plugin and
    use it in the Helm setup:

    @rule
    def download_myplugin_plugin_request(
        _: MyPluginBinding, subsystem: MyHelmPluginSubsystem
    ) -> ExternalHelmPluginRequest:
        return ExternalHelmPluginRequest.from_subsystem(subsystem, platform)


    def rules():
        return [
            *collect_rules(),
            UnionRule(ExternalHelmPluginBinding, MyPluginBinding),
        ]
    """


@dataclass(frozen=True)
class HelmPluginPlatformCommand:
    os: str
    arch: str
    command: str

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> HelmPluginPlatformCommand:
        return cls(**snake_case_attr_dict(d))


@dataclass(frozen=True)
class HelmPluginInfo:
    name: str
    version: str
    usage: str | None = None
    description: str | None = None
    ignore_flags: bool | None = None
    command: str | None = None
    platform_command: tuple[HelmPluginPlatformCommand, ...] = dataclasses.field(
        default_factory=tuple
    )
    hooks: FrozenDict[str, str] = dataclasses.field(default_factory=FrozenDict)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> HelmPluginInfo:
        platform_command = [
            HelmPluginPlatformCommand.from_dict(d) for d in d.pop("platformCommand", [])
        ]
        hooks = d.pop("hooks", {})

        attrs = snake_case_attr_dict(d)
        return cls(platform_command=tuple(platform_command), hooks=FrozenDict(hooks), **attrs)

    @classmethod
    def from_bytes(cls, content: bytes) -> HelmPluginInfo:
        return HelmPluginInfo.from_dict(yaml.safe_load(content))


_ExternalHelmPlugin = TypeVar("_ExternalHelmPlugin", bound=ExternalHelmPlugin)
_EHPB = TypeVar("_EHPB", bound="ExternalHelmPluginBinding")


@union(in_scope_types=[EnvironmentName])
@dataclass(frozen=True)
class ExternalHelmPluginBinding(Generic[_ExternalHelmPlugin], metaclass=ABCMeta):
    """Union type allowing Pants to discover global external Helm plugins."""

    plugin_subsystem_cls: ClassVar[Type[ExternalHelmPlugin]]

    name: str

    @final
    @classmethod
    def create(cls: Type[_EHPB]) -> _EHPB:
        return cls(name=cls.plugin_subsystem_cls.plugin_name)


@dataclass(frozen=True)
class ExternalHelmPluginRequest(EngineAwareParameter):
    """Helper class to create a download request for an external Helm plugin."""

    plugin_name: str
    platform: Platform

    _tool_request: ExternalToolRequest

    @classmethod
    def from_subsystem(
        cls, subsystem: ExternalHelmPlugin, platform: Platform
    ) -> ExternalHelmPluginRequest:
        return cls(
            plugin_name=subsystem.plugin_name,
            platform=platform,
            _tool_request=subsystem.get_request(platform),
        )

    def debug_hint(self) -> str | None:
        return self.plugin_name

    def metadata(self) -> dict[str, Any] | None:
        return {"platform": self.platform, "url": self._tool_request.download_file_request.url}


@dataclass(frozen=True)
class HelmPlugin(EngineAwareReturnType):
    info: HelmPluginInfo
    platform: Platform
    snapshot: Snapshot

    @property
    def name(self) -> str:
        return self.info.name

    @property
    def version(self) -> str:
        return self.info.version

    def level(self) -> LogLevel | None:
        return LogLevel.DEBUG

    def message(self) -> str | None:
        return f"Materialized Helm plugin {self.name} with version {self.version} for {self.platform} platform."

    def metadata(self) -> dict[str, Any] | None:
        return {"name": self.name, "version": self.version, "platform": self.platform}

    def artifacts(self) -> dict[str, FileDigest | Snapshot] | None:
        return {"content": self.snapshot}

    def cacheable(self) -> bool:
        return True


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


@rule(desc="Download external Helm plugin", level=LogLevel.DEBUG)
async def download_external_helm_plugin(request: ExternalHelmPluginRequest) -> HelmPlugin:
    downloaded_tool = await Get(DownloadedExternalTool, ExternalToolRequest, request._tool_request)

    plugin_info_file = await Get(
        Digest,
        DigestSubset(
            downloaded_tool.digest,
            PathGlobs(
                ["plugin.yaml", "plugin.yml"],
                glob_match_error_behavior=GlobMatchErrorBehavior.error,
                description_of_origin=request.plugin_name,
            ),
        ),
    )
    plugin_info_contents = await Get(DigestContents, Digest, plugin_info_file)
    if len(plugin_info_contents) == 0:
        raise HelmPluginMetadataFileNotFound(request.plugin_name)

    plugin_info = HelmPluginInfo.from_bytes(plugin_info_contents[0].content)
    if not plugin_info.command and not plugin_info.platform_command:
        raise HelmPluginMissingCommand(request.plugin_name)

    plugin_snapshot = await Get(Snapshot, Digest, downloaded_tool.digest)
    return HelmPlugin(info=plugin_info, platform=request.platform, snapshot=plugin_snapshot)


# ---------------------------------------------
# Helm Binary setup
# ---------------------------------------------


@dataclass(frozen=True)
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
        object.__setattr__(self, "path", path)
        object.__setattr__(self, "immutable_input_digests", FrozenDict(immutable_input_digests))
        object.__setattr__(self, "env", FrozenDict({**helm_env, **local_env}))

    @property
    def config_digest(self) -> Digest:
        return self.immutable_input_digests[_HELM_CONFIG_DIR]

    @property
    def data_digest(self) -> Digest:
        return self.immutable_input_digests[_HELM_DATA_DIR]

    @property
    def append_only_caches(self) -> dict[str, str]:
        return {_HELM_CACHE_NAME: _HELM_CACHE_DIR}


@dataclass(frozen=True)
class HelmProcess:
    argv: tuple[str, ...]
    input_digest: Digest
    description: str = dataclasses.field(compare=False)
    level: LogLevel
    extra_env: FrozenDict[str, str]
    extra_immutable_input_digests: FrozenDict[str, Digest]
    extra_append_only_caches: FrozenDict[str, str]
    cache_scope: ProcessCacheScope | None
    timeout_seconds: int | None
    output_directories: tuple[str, ...]
    output_files: tuple[str, ...]

    def __init__(
        self,
        argv: Iterable[str],
        *,
        description: str,
        input_digest: Digest = EMPTY_DIGEST,
        level: LogLevel = LogLevel.INFO,
        output_directories: Iterable[str] | None = None,
        output_files: Iterable[str] | None = None,
        extra_env: Mapping[str, str] | None = None,
        extra_immutable_input_digests: Mapping[str, Digest] | None = None,
        extra_append_only_caches: Mapping[str, str] | None = None,
        cache_scope: ProcessCacheScope | None = None,
        timeout_seconds: int | None = None,
    ):
        object.__setattr__(self, "argv", tuple(argv))
        object.__setattr__(self, "input_digest", input_digest)
        object.__setattr__(self, "description", description)
        object.__setattr__(self, "level", level)
        object.__setattr__(self, "output_directories", tuple(output_directories or ()))
        object.__setattr__(self, "output_files", tuple(output_files or ()))
        object.__setattr__(self, "extra_env", FrozenDict(extra_env or {}))
        object.__setattr__(
            self, "extra_immutable_input_digests", FrozenDict(extra_immutable_input_digests or {})
        )
        object.__setattr__(
            self, "extra_append_only_caches", FrozenDict(extra_append_only_caches or {})
        )
        object.__setattr__(self, "cache_scope", cache_scope)
        object.__setattr__(self, "timeout_seconds", timeout_seconds)


@rule(desc="Download and configure Helm", level=LogLevel.DEBUG)
async def setup_helm(
    helm_subsytem: HelmSubsystem, global_plugins: HelmPlugins, platform: Platform
) -> HelmBinary:
    downloaded_binary, empty_dirs_digest = await MultiGet(
        Get(DownloadedExternalTool, ExternalToolRequest, helm_subsytem.get_request(platform)),
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
        logger.debug(f"Installing {pluralize(len(global_plugins), 'global Helm plugin')}.")
        prefixed_plugins_digests = await MultiGet(
            Get(
                Digest,
                AddPrefix(
                    plugin.snapshot.digest, os.path.join(_HELM_DATA_DIR, "plugins", plugin.name)
                ),
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

    local_env = await Get(EnvironmentVars, EnvironmentVarsRequest(["HOME", "PATH"]))
    return HelmBinary(
        path=helm_path,
        helm_env=helm_env,
        local_env=local_env,
        immutable_input_digests=setup_immutable_digests,
    )


@rule
async def helm_process(
    request: HelmProcess,
    helm_binary: HelmBinary,
    helm_subsystem: HelmSubsystem,
) -> Process:
    global_extra_env = await Get(
        EnvironmentVars, EnvironmentVarsRequest(helm_subsystem.extra_env_vars)
    )

    # Helm binary's setup parameters go last to prevent end users overriding any of its values.

    env = {**global_extra_env, **request.extra_env, **helm_binary.env}
    immutable_input_digests = {
        **request.extra_immutable_input_digests,
        **helm_binary.immutable_input_digests,
    }
    append_only_caches = {**request.extra_append_only_caches, **helm_binary.append_only_caches}

    argv = [helm_binary.path, *request.argv]

    # A special case for "--debug".
    # This ensures that it is applied to all operations in the chain,
    # not just the final one.
    # For example, we want this applied to the call to `template`, not just the call to `install`
    # Also, we can be helpful and automatically forward a request to debug Pants to also debug Helm
    debug_requested = "--debug" in helm_subsystem.valid_args() or (
        0 < logger.getEffectiveLevel() <= LogLevel.DEBUG.level
    )
    if debug_requested and "--debug" not in request.argv:
        argv.append("--debug")

    return Process(
        argv,
        input_digest=request.input_digest,
        immutable_input_digests=immutable_input_digests,
        env=env,
        description=request.description,
        level=request.level,
        append_only_caches=append_only_caches,
        output_directories=request.output_directories,
        output_files=request.output_files,
        cache_scope=request.cache_scope or ProcessCacheScope.SUCCESSFUL,
        timeout_seconds=request.timeout_seconds,
    )


def rules():
    return [*collect_rules(), *external_tool.rules(), *process.rules()]
