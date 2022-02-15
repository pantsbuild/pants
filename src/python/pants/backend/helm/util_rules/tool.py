# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
import re
from abc import ABCMeta
from dataclasses import dataclass
from enum import Enum
from pathlib import PurePath
from typing import ClassVar, Iterable, Mapping, Type, TypeVar, cast

from typing_extensions import final

from pants.backend.helm.subsystem import HelmSubsystem
from pants.core.util_rules.external_tool import (
    DownloadedExternalTool,
    ExternalToolRequest,
    TemplatedExternalTool,
)
from pants.engine.environment import Environment, EnvironmentRequest
from pants.engine.fs import (
    EMPTY_DIGEST,
    EMPTY_SNAPSHOT,
    AddPrefix,
    CreateDigest,
    Digest,
    DigestSubset,
    Directory,
    MergeDigests,
    PathGlobs,
    RemovePrefix,
    Snapshot,
)
from pants.engine.platform import Platform
from pants.engine.process import Process, ProcessCacheScope, ProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.unions import UnionMembership, union
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.meta import frozen_after_init


class InstallOutputFormat(Enum):
    TABLE = "table"
    JSON = "json"
    YAML = "yaml"


@frozen_after_init
@dataclass(unsafe_hash=True)
class HelmBinary:
    path: str
    repositories: tuple[str, ...]

    env: FrozenDict[str, str]

    cache_dir: str
    config_dir: str
    data_dir: str

    loaded_plugins: tuple[str, ...]

    _options: HelmSubsystem
    _setup_digests: FrozenDict[str, Digest]

    def __init__(
        self,
        path: str,
        *,
        repositories: Iterable[str],
        cache_dir: str,
        config_dir: str,
        data_dir: str,
        local_env: FrozenDict[str, str],
        setup_digests: dict[str, Digest],
        loaded_plugins: Iterable[str],
        options: HelmSubsystem,
    ) -> None:
        self.path = path
        self.repositories = tuple(repositories)
        self.cache_dir = cache_dir
        self.config_dir = config_dir
        self.data_dir = data_dir
        self._setup_digests = FrozenDict(setup_digests)
        self.loaded_plugins = tuple(loaded_plugins)
        self._options = options
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
        immutable_input_digests: dict[str, Digest] = {},
        output_directories: Iterable[str] = (),
        cache_scope: ProcessCacheScope = ProcessCacheScope.SUCCESSFUL,
    ) -> Process:
        argv = [self.path]
        argv.extend(args)

        return Process(
            argv,
            env=self.env,
            description=description,
            level=level,
            input_digest=input_digest,
            output_directories=output_directories,
            immutable_input_digests={**self._setup_digests, **immutable_input_digests},
            cache_scope=cache_scope,
        )

    def lint(
        self, *, chart: str, path: str, chart_digest: Digest, strict: bool | None = None
    ) -> Process:
        args = ["lint", path]
        if strict is None:
            strict = self._options.strict
        if strict:
            args.append("--strict")

        return self._cmd(
            args,
            input_digest=chart_digest,
            description=f"Linting Helm chart: {chart}",
        )

    def package(self, *, chart: str, path: str, chart_digest: Digest, output_dir: str) -> Process:
        return self._cmd(
            ["package", path, "-d", output_dir],
            input_digest=chart_digest,
            description=f"Packaging Helm chart: {chart}",
            output_directories=(output_dir,),
        )

    def template(
        self,
        *,
        release_name: str,
        path: str,
        chart_digest: Digest,
        output_dir: str,
        api_versions: Iterable[str] = (),
        kube_version: str | None = None,
        skip_tests: bool = False,
        value_files: Snapshot = EMPTY_SNAPSHOT,
        values: Mapping[str, str] = {},
    ) -> Process:
        values_prefix = "__values"
        args = ["template", release_name, path, "--output-dir", output_dir]
        if len(list(api_versions)) > 0:
            args.extend(["--api-versions", ",".join(list(api_versions))])
        if kube_version:
            args.extend(["--kube-version", kube_version])
        if skip_tests:
            args.append("--skip-tests")
        for file in value_files.files:
            args.extend(["--values", os.path.join(values_prefix, file)])
        for key, value in values.items():
            args.extend(["--set", f"{key}={value}"])

        return self._cmd(
            args,
            input_digest=chart_digest,
            immutable_input_digests={values_prefix: value_files.digest},
            output_directories=(output_dir,),
            description=f"Rendering Helm release '{release_name}' contents from chart at: {path}",
        )

    def pull(self, url: str, *, version: str, dest_dir: str, dest_digest: Digest) -> Process:
        return self._cmd(
            ["pull", url, "--version", version, "--destination", dest_dir, "--untar"],
            output_directories=(dest_dir,),
            input_digest=dest_digest,
            description=f"Pulling Helm Chart {url} with version {version}",
        )

    def push(
        self, *, chart: str, version: str, path: str, digest: Digest, oci_registry: str
    ) -> Process:
        return self._cmd(
            ["push", path, oci_registry],
            input_digest=digest,
            description=f"Pushing Helm chart '{chart}' with version '{version}' into OCI registry: {oci_registry}",
        )

    def upgrade(
        self,
        release_name: str,
        *,
        path: str,
        install: bool = False,
        description: str | None = None,
        create_namespace: bool = False,
        namespace: str | None = None,
        chart_version: str | None = None,
        chart_digest: Digest = EMPTY_DIGEST,
        output_format: InstallOutputFormat = InstallOutputFormat.TABLE,
        value_files: Snapshot = EMPTY_SNAPSHOT,
        values: Mapping[str, str] = {},
        skip_crds: bool = False,
        timeout: str | None = None,
        extra_args: list[str] = [],
    ) -> Process:
        values_prefix = "__values"
        args = ["upgrade", release_name, path]

        if install:
            args.append("--install")
        if chart_version:
            args.extend(["--version", chart_version])
        if description:
            args.extend(["--description", description])
        if namespace:
            args.extend(["--namespace", namespace])
        if create_namespace:
            args.append("--create-namespace")
        if skip_crds:
            args.append("--skip-crds")
        if timeout:
            args.extend(["--timeout", timeout])

        args.extend(["--output", output_format.value])

        for key, value in values.items():
            args.extend(["--set", f"{key}={value}"])

        def sorted_file_names() -> list[str]:
            if not value_files.files:
                return []

            paths = map(lambda a: PurePath(a), list(value_files.files))
            non_overrides = []
            overrides = []
            for p in paths:
                if "override" in p.name.lower():
                    overrides.append(p)
                else:
                    non_overrides.append(p)

            def by_path_length(p: PurePath) -> int:
                if not p.parents:
                    return 0
                return len(p.parents)

            non_overrides.sort(key=by_path_length)
            overrides.sort(key=by_path_length)
            return list(map(lambda a: str(a), [*non_overrides, *overrides]))

        for file in sorted_file_names():
            args.extend(["--values", os.path.join(values_prefix, file)])

        args.extend(extra_args)

        return self._cmd(
            args,
            input_digest=chart_digest,
            immutable_input_digests={values_prefix: value_files.digest},
            description=f"Installing release '{release_name}' using chart: {path}",
        )

    def run_plugin(
        self,
        plugin: HelmPlugin,
        args: Iterable[str],
        *,
        description: str,
        input_digest: Digest,
        output_dirs: tuple[str, ...] = (),
        cache_scope: ProcessCacheScope = ProcessCacheScope.SUCCESSFUL,
    ) -> Process:
        return self._cmd(
            [plugin.plugin_name, *args],
            input_digest=input_digest,
            description=description,
            output_directories=output_dirs,
            level=LogLevel.DEBUG,
            cache_scope=cache_scope,
        )


class HelmPlugin(TemplatedExternalTool, metaclass=ABCMeta):
    plugin_name: ClassVar[str]


_DHPR = TypeVar("_DHPR", bound="DownloadHelmPluginRequest")


@union
@dataclass(frozen=True)
class DownloadHelmPluginRequest(metaclass=ABCMeta):
    plugin_type: ClassVar[Type[HelmPlugin]]

    name: str

    @final
    @classmethod
    def create(cls: Type[_DHPR]) -> _DHPR:
        return cls(name=cls.plugin_type.plugin_name)


@dataclass(frozen=True)
class DownloadedHelmPlugin:
    name: str
    version: str
    digest: Digest

    @classmethod
    def from_downloaded_external_tool(
        cls, plugin: HelmPlugin, tool: DownloadedExternalTool
    ) -> DownloadedHelmPlugin:
        return cls(name=plugin.plugin_name, version=plugin.version, digest=tool.digest)


def _build_helm_env(cache_dir: str, config_dir: str, data_dir: str) -> FrozenDict[str, str]:
    return FrozenDict(
        {
            "HELM_CACHE_HOME": cache_dir,
            "HELM_CONFIG_HOME": config_dir,
            "HELM_DATA_HOME": data_dir,
            "HELM_EXPERIMENTAL_OCI": "1",
        }
    )


@rule(desc="Initialise Helm", level=LogLevel.DEBUG)
async def setup_helm(
    helm_options: HelmSubsystem,
    union_membership: UnionMembership,
) -> HelmBinary:
    cache_dir = "__cache"
    config_dir = "__config"
    data_dir = "__data"

    downloaded_binary, cache_digest, config_digest, data_digest = await MultiGet(
        Get(
            DownloadedExternalTool, ExternalToolRequest, helm_options.get_request(Platform.current)
        ),
        Get(Digest, CreateDigest([Directory(cache_dir)])),
        Get(Digest, CreateDigest([Directory(config_dir)])),
        Get(Digest, CreateDigest([Directory(data_dir)])),
    )

    tool_relpath = "__helm"
    immutable_input_digests = {tool_relpath: downloaded_binary.digest}
    helm_path = f"{tool_relpath}/{downloaded_binary.exe}"

    output_dirs = (cache_dir, config_dir, data_dir)

    def create_process(args: list[str], *, description: str, input_digest: Digest) -> Process:
        return Process(
            [helm_path, *args],
            env=_build_helm_env(cache_dir, config_dir, data_dir),
            input_digest=input_digest,
            immutable_input_digests=immutable_input_digests,
            output_directories=output_dirs,
            description=description,
            level=LogLevel.DEBUG,
        )

    mutable_input_digest = await Get(
        Digest, MergeDigests([cache_digest, config_digest, data_digest])
    )

    # Initialise Helm with the preconfigured 'classic' repositories
    helm_registries = helm_options.registries()
    classic_repositories = helm_registries.all_classic()
    if classic_repositories:
        for repo in classic_repositories:
            args = ["repo", "add", repo.alias, repo.address]
            result = await Get(
                ProcessResult,
                Process,
                create_process(
                    args,
                    description=f"Adding Helm 3rd party repository '{repo.alias}' at: {repo.address}",
                    input_digest=mutable_input_digest,
                ),
            )
            mutable_input_digest = result.output_digest

        update_index_result = await Get(
            ProcessResult,
            Process,
            create_process(
                ["repo", "update"],
                description="Update Helm repository indexes",
                input_digest=mutable_input_digest,
            ),
        )
        mutable_input_digest = update_index_result.output_digest

    # Install Global Helm Plugins
    loaded_plugins = []
    if union_membership.has_members(DownloadHelmPluginRequest):
        download_helm_plugin_request_types = cast(
            "Iterable[type[DownloadHelmPluginRequest]]",
            union_membership[DownloadHelmPluginRequest] or (),
        )
        downloaded_plugins = await MultiGet(
            Get(DownloadedHelmPlugin, DownloadHelmPluginRequest, request_type.create())
            for request_type in download_helm_plugin_request_types
        )
        if downloaded_plugins:
            downloaded_plugin_and_names = zip(
                [plugin.name for plugin in downloaded_plugins], downloaded_plugins
            )
            prefixed_plugins_digeests = await MultiGet(
                Get(Digest, AddPrefix(binary.digest, f"{data_dir}/plugins/{prefix}"))
                for prefix, binary in downloaded_plugin_and_names
            )
            plugins_digests = await Get(
                Digest, MergeDigests([digest for digest in prefixed_plugins_digeests])
            )
            mutable_input_digest = await Get(
                Digest, MergeDigests([mutable_input_digest, plugins_digests])
            )

            list_plugins_result = await Get(
                ProcessResult,
                Process,
                create_process(
                    ["plugin", "ls"],
                    description="Verify installation of Helm plugins",
                    input_digest=mutable_input_digest,
                ),
            )
            plugin_table = list_plugins_result.stdout.decode().splitlines()[1:]
            loaded_plugins = [re.split(r"\t+", line.rstrip())[0] for line in plugin_table]

    updated_cache_digest, updated_config_digest, updated_data_digest = await MultiGet(
        Get(Digest, DigestSubset(mutable_input_digest, PathGlobs([f"{cache_dir}/**"]))),
        Get(Digest, DigestSubset(mutable_input_digest, PathGlobs([f"{config_dir}/**"]))),
        Get(Digest, DigestSubset(mutable_input_digest, PathGlobs([f"{data_dir}/**"]))),
    )
    cache_subset_digest, config_subset_digest, data_subset_digest = await MultiGet(
        Get(Digest, RemovePrefix(updated_cache_digest, cache_dir)),
        Get(Digest, RemovePrefix(updated_config_digest, config_dir)),
        Get(Digest, RemovePrefix(updated_data_digest, data_dir)),
    )
    setup_inmutable_digests = {
        **immutable_input_digests,
        cache_dir: cache_subset_digest,
        config_dir: config_subset_digest,
        data_dir: data_subset_digest,
    }

    local_env = await Get(Environment, EnvironmentRequest(["HOME", "PATH"]))
    return HelmBinary(
        path=helm_path,
        repositories=[f"@{repo.alias}" for repo in classic_repositories],
        cache_dir=cache_dir,
        config_dir=config_dir,
        data_dir=data_dir,
        local_env=local_env,
        setup_digests=setup_inmutable_digests,
        loaded_plugins=loaded_plugins,
        options=helm_options,
    )


def rules():
    return collect_rules()
