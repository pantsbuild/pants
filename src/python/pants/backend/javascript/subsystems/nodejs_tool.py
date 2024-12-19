# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar, Iterable, Mapping

from pants.backend.javascript import install_node_package, nodejs_project_environment
from pants.backend.javascript.install_node_package import (
    InstalledNodePackage,
    InstalledNodePackageRequest,
)
from pants.backend.javascript.nodejs_project_environment import NodeJsProjectEnvironmentProcess
from pants.backend.javascript.package_manager import PackageManager
from pants.backend.javascript.resolve import FirstPartyNodePackageResolves, NodeJSProjectResolves
from pants.backend.javascript.subsystems.nodejs import NodeJS, NodeJSToolProcess
from pants.engine.internals.native_engine import Digest, MergeDigests
from pants.engine.internals.selectors import Get
from pants.engine.process import Process
from pants.engine.rules import Rule, collect_rules, rule
from pants.engine.unions import UnionRule
from pants.option.option_types import StrOption
from pants.option.subsystem import Subsystem
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.strutil import softwrap


class NodeJSToolBase(Subsystem):
    # Subclasses must set.
    default_version: ClassVar[str]

    version = StrOption(
        advanced=True,
        default=lambda cls: cls.default_version,
        help="Version string for the tool in the form package@version (e.g. prettier@2.6.2)",
    )

    install_from_resolve = StrOption(
        advanced=True,
        default=None,
        help=lambda cls: softwrap(
            f"""\
            If specified, install the tool using the lockfile for this named resolve,
            instead of the version configured in this subsystem.

            If unspecified, the tool will use the default configured package manager
            [{NodeJS.options_scope}].package_manager`, and install the tool without a
            lockfile.
            """
        ),
    )

    def request(
        self,
        args: tuple[str, ...],
        input_digest: Digest,
        description: str,
        level: LogLevel,
        output_files: tuple[str, ...] = (),
        output_directories: tuple[str, ...] = (),
        append_only_caches: FrozenDict[str, str] | None = None,
        timeout_seconds: int | None = None,
        extra_env: Mapping[str, str] | None = None,
    ) -> NodeJSToolRequest:
        return NodeJSToolRequest(
            tool=self.version,
            resolve=self.install_from_resolve,
            args=args,
            input_digest=input_digest,
            description=description,
            level=level,
            output_files=output_files,
            output_directories=output_directories,
            append_only_caches=append_only_caches or FrozenDict(),
            timeout_seconds=timeout_seconds,
            extra_env=extra_env or FrozenDict(),
            options_scope=self.options_scope,
        )


@dataclass(frozen=True)
class NodeJSToolRequest:
    tool: str
    resolve: str | None
    args: tuple[str, ...]
    input_digest: Digest
    description: str
    level: LogLevel
    options_scope: str
    output_files: tuple[str, ...] = ()
    output_directories: tuple[str, ...] = ()
    append_only_caches: FrozenDict[str, str] = field(default_factory=FrozenDict)
    timeout_seconds: int | None = None
    extra_env: Mapping[str, str] = field(default_factory=FrozenDict)


async def _run_tool_without_resolve(request: NodeJSToolRequest) -> Process:
    nodejs = await Get(NodeJS)

    pkg_manager_version = nodejs.package_managers.get(nodejs.package_manager)
    pkg_manager_and_version = nodejs.default_package_manager
    if pkg_manager_version is None or pkg_manager_and_version is None:
        # Occurs when a user configures a custom package manager but without a resolve.
        # Corepack requires a package.json to make a decision on a "good known release".
        raise ValueError(
            softwrap(
                f"""
                Version for {nodejs.package_manager} has to be configured
                in [{nodejs.options_scope}].package_managers when running
                the tool '{request.tool}' without setting [{request.options_scope}].install_from_resolve.
                """
            )
        )
    pkg_manager = PackageManager.from_string(pkg_manager_and_version)

    return await Get(
        Process,
        NodeJSToolProcess(
            pkg_manager.name,
            pkg_manager.version,
            args=(*pkg_manager.download_and_execute_args, request.tool, *request.args),
            description=request.description,
            input_digest=request.input_digest,
            output_files=request.output_files,
            output_directories=request.output_directories,
            append_only_caches=request.append_only_caches,
            timeout_seconds=request.timeout_seconds,
            extra_env=FrozenDict({**pkg_manager.extra_env, **request.extra_env}),
        ),
    )


async def _run_tool_with_resolve(request: NodeJSToolRequest, resolve: str) -> Process:
    resolves = await Get(NodeJSProjectResolves)

    if request.resolve not in resolves:
        reason = (
            f"Available resolves are {', '.join(resolves.keys())}."
            if resolves
            else "This project contains no resolves."
        )
        raise ValueError(f"{resolve} is not a named NodeJS resolve. {reason}")

    all_first_party = await Get(FirstPartyNodePackageResolves)
    package_for_resolve = all_first_party[resolve]
    project = resolves[resolve]
    installed = await Get(
        InstalledNodePackage, InstalledNodePackageRequest(package_for_resolve.address)
    )
    request_tool_without_version = request.tool.partition("@")[0]
    return await Get(
        Process,
        NodeJsProjectEnvironmentProcess(
            env=installed.project_env,
            args=(
                *project.package_manager.execute_args,
                request_tool_without_version,
                *request.args,
            ),
            description=request.description,
            input_digest=await Get(Digest, MergeDigests([request.input_digest, installed.digest])),
            output_files=request.output_files,
            output_directories=request.output_directories,
            per_package_caches=request.append_only_caches,
            timeout_seconds=request.timeout_seconds,
            extra_env=FrozenDict(request.extra_env),
        ),
    )


@rule
async def prepare_tool_process(request: NodeJSToolRequest) -> Process:
    if request.resolve is None:
        return await _run_tool_without_resolve(request)
    return await _run_tool_with_resolve(request, request.resolve)


def rules() -> Iterable[Rule | UnionRule]:
    return [*collect_rules(), *nodejs_project_environment.rules(), *install_node_package.rules()]
