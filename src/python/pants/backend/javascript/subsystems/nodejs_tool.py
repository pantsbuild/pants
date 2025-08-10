# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import ClassVar

from pants.backend.javascript import install_node_package, nodejs_project_environment
from pants.backend.javascript.install_node_package import (
    InstalledNodePackageRequest,
    install_node_packages_for_address,
)
from pants.backend.javascript.nodejs_project_environment import (
    NodeJsProjectEnvironmentProcess,
    setup_nodejs_project_environment_process,
)
from pants.backend.javascript.package_manager import PackageManager
from pants.backend.javascript.resolve import (
    resolve_to_first_party_node_package,
    resolve_to_projects,
)
from pants.backend.javascript.subsystems.nodejs import (
    NodeJS,
    NodeJSToolProcess,
    setup_node_tool_process,
)
from pants.engine.internals.native_engine import Digest, MergeDigests
from pants.engine.internals.selectors import Get
from pants.engine.intrinsics import merge_digests
from pants.engine.process import Process
from pants.engine.rules import Rule, collect_rules, implicitly, rule
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
        help="Version string for the tool in the form package@version (e.g. prettier@3.5.2)",
    )

    _binary_name = StrOption(
        advanced=True,
        default=None,
        help="Override the binary to run for this tool. Defaults to the package name.",
    )

    @property
    def binary_name(self) -> str:
        """The binary name to run for this tool."""
        if self._binary_name:
            return self._binary_name

        # For scoped packages (@scope/package), use the scope name (often matches the binary)
        # For regular packages, use the full package name
        match = re.match(r"^(?:@([^/]+)/[^@]+|([^@]+))", self.version)
        if not match:
            raise ValueError(f"Invalid npm package specification: {self.version}")
        return match.group(1) or match.group(2)

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
        project_caches: FrozenDict[str, str] | None = None,
        timeout_seconds: int | None = None,
        extra_env: Mapping[str, str] | None = None,
    ) -> NodeJSToolRequest:
        return NodeJSToolRequest(
            package=self.version,
            binary_name=self.binary_name,
            resolve=self.install_from_resolve,
            args=args,
            input_digest=input_digest,
            description=description,
            level=level,
            output_files=output_files,
            output_directories=output_directories,
            append_only_caches=append_only_caches or FrozenDict(),
            project_caches=project_caches or FrozenDict(),
            timeout_seconds=timeout_seconds,
            extra_env=extra_env or FrozenDict(),
            options_scope=self.options_scope,
        )


@dataclass(frozen=True)
class NodeJSToolRequest:
    package: str
    binary_name: str
    resolve: str | None
    args: tuple[str, ...]
    input_digest: Digest
    description: str
    level: LogLevel
    options_scope: str
    output_files: tuple[str, ...] = ()
    output_directories: tuple[str, ...] = ()
    append_only_caches: FrozenDict[str, str] = field(default_factory=FrozenDict)
    project_caches: FrozenDict[str, str] = field(default_factory=FrozenDict)
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
                the tool '{request.binary_name}' without setting [{request.options_scope}].install_from_resolve.
                """
            )
        )
    pkg_manager = PackageManager.from_string(pkg_manager_and_version)

    return await setup_node_tool_process(
        NodeJSToolProcess(
            pkg_manager.name,
            pkg_manager.version,
            args=pkg_manager.make_download_and_execute_args(
                request.package,
                request.binary_name,
                request.args,
            ),
            description=request.description,
            input_digest=request.input_digest,
            output_files=request.output_files,
            output_directories=request.output_directories,
            append_only_caches=request.append_only_caches,
            timeout_seconds=request.timeout_seconds,
            extra_env=FrozenDict({**pkg_manager.extra_env, **request.extra_env}),
        ),
        **implicitly(),
    )


async def _run_tool_with_resolve(request: NodeJSToolRequest, resolve: str) -> Process:
    resolves = await resolve_to_projects(**implicitly())

    if request.resolve not in resolves:
        reason = (
            f"Available resolves are {', '.join(resolves.keys())}."
            if resolves
            else "This project contains no resolves."
        )
        raise ValueError(f"{resolve} is not a named NodeJS resolve. {reason}")

    all_first_party = await resolve_to_first_party_node_package(**implicitly())
    package_for_resolve = all_first_party[resolve]
    project = resolves[resolve]

    installed = await install_node_packages_for_address(
        InstalledNodePackageRequest(package_for_resolve.address), **implicitly()
    )
    # Merge the tool's input files (source code, config files) with the installed
    # packages (node_modules). This is required for resolve-based execution where tools like
    # TypeScript need both their input files AND the installed dependencies in the sandbox.
    merged_input_digest = await merge_digests(
        MergeDigests([request.input_digest, installed.digest])
    )

    return await setup_nodejs_project_environment_process(
        NodeJsProjectEnvironmentProcess(
            env=installed.project_env,
            args=(*project.package_manager.execute_args, request.binary_name, *request.args),
            description=request.description,
            input_digest=merged_input_digest,
            output_files=request.output_files,
            output_directories=request.output_directories,
            per_package_caches=request.append_only_caches,
            project_caches=request.project_caches,
            timeout_seconds=request.timeout_seconds,
            extra_env=FrozenDict(request.extra_env),
        ),
        **implicitly(),
    )


@rule
async def prepare_tool_process(request: NodeJSToolRequest) -> Process:
    if request.resolve is None:
        return await _run_tool_without_resolve(request)
    return await _run_tool_with_resolve(request, request.resolve)


def rules() -> Iterable[Rule | UnionRule]:
    return [*collect_rules(), *nodejs_project_environment.rules(), *install_node_package.rules()]
