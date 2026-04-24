# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import importlib.resources
import json
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
from pants.engine.fs import CreateDigest, FileContent, GlobMatchErrorBehavior, PathGlobs
from pants.engine.internals.native_engine import Digest, MergeDigests
from pants.engine.intrinsics import (
    create_digest,
    get_digest_contents,
    merge_digests,
    path_globs_to_digest,
)
from pants.engine.process import Process, fallible_to_exec_result_or_raise
from pants.engine.rules import Rule, collect_rules, implicitly, rule
from pants.engine.unions import UnionRule
from pants.core.goals.generate_lockfiles import DEFAULT_TOOL_LOCKFILE
from pants.core.goals.resolves import ExportableTool
from pants.option.option_types import StrOption
from pants.option.subsystem import Subsystem
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.strutil import softwrap


class NodeJSToolBase(Subsystem, ExportableTool):
    # Subclasses must set.
    default_version: ClassVar[str]

    # Mapping of package manager name to (python_package, filename) for bundled lockfiles.
    # e.g. {"npm": ("pants.backend.javascript.lint.prettier", "prettier.package-lock.json"), ...}
    default_lockfile_resources: ClassVar[dict[str, tuple[str, str]] | None] = None

    # Set to False for tools that always use a resolve (e.g. TypeScript).
    lockfile_required: ClassVar[bool] = True

    version = StrOption(
        advanced=True,
        default=lambda cls: cls.default_version,
        help="Version string for the tool in the form package@version (e.g. prettier@3.6.2)",
    )

    _binary_name = StrOption(
        advanced=True,
        default=None,
        help="Override the binary to run for this tool. Defaults to the package name.",
    )

    lockfile = StrOption(
        advanced=True,
        default=lambda cls: DEFAULT_TOOL_LOCKFILE if cls.default_lockfile_resources else None,
        help=lambda cls: softwrap(
            f"""\
            Path to a lockfile for the tool's npm dependencies. If set to
            `{DEFAULT_TOOL_LOCKFILE}`, the bundled lockfile will be used. If set to a
            file path, that lockfile will be used instead. If set to `None` or empty
            string, no lockfile will be used and the tool will be installed without
            pinned transitive dependencies.
            """
        ),
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

    def __init__(self, *args, **kwargs):
        if self.lockfile_required and not self.default_lockfile_resources:
            raise ValueError(
                softwrap(
                    f"""
                    The class property `default_lockfile_resources` must be set for
                    `{self.options_scope}`, or set `lockfile_required = False` to opt out.
                    """
                )
            )
        super().__init__(*args, **kwargs)

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
            lockfile=self.lockfile if self.lockfile else None,
            default_lockfile_resources=FrozenDict(self.default_lockfile_resources)
            if self.default_lockfile_resources
            else None,
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
    lockfile: str | None
    default_lockfile_resources: FrozenDict[str, tuple[str, str]] | None
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


def _parse_package_name_and_version(package: str) -> tuple[str, str]:
    try:
        if package.startswith("@"):
            # Scoped packages (@scope/name@version): skip the leading @ and find the separator.
            at_idx = package.index("@", 1)
            return package[:at_idx], package[at_idx + 1 :]
        else:
            at_idx = package.index("@")
            return package[:at_idx], package[at_idx + 1 :]
    except ValueError:
        raise ValueError(
            f"Invalid npm package specification '{package}': expected format 'package@version' "
            f"or '@scope/package@version'."
        )


@dataclass(frozen=True)
class _NodeJSUserLockfileRequest:
    path: str
    description_of_origin: str


@dataclass(frozen=True)
class _NodeJSLockfileContents:
    content: bytes


@rule
async def read_nodejs_tool_user_lockfile(
    request: _NodeJSUserLockfileRequest,
) -> _NodeJSLockfileContents:
    digest = await path_globs_to_digest(
        PathGlobs(
            [request.path],
            glob_match_error_behavior=GlobMatchErrorBehavior.error,
            description_of_origin=request.description_of_origin,
        )
    )
    contents = await get_digest_contents(digest)
    return _NodeJSLockfileContents(contents[0].content)


@dataclass(frozen=True)
class _NodeJSBundledToolInstallRequest:
    pkg_manager_name: str
    pkg_manager_version: str
    lockfile_name: str
    lockfile_bytes: bytes
    package_name: str
    package_version: str
    options_scope: str
    extra_env: FrozenDict[str, str]
    timeout_seconds: int | None


@dataclass(frozen=True)
class _NodeJSBundledToolInstalled:
    digest: Digest


@rule
async def install_nodejs_tool_from_bundled_lockfile(
    request: _NodeJSBundledToolInstallRequest,
) -> _NodeJSBundledToolInstalled:
    package_json = json.dumps(
        {
            "name": f"pants-tool-{request.options_scope}",
            "private": True,
            "dependencies": {request.package_name: request.package_version},
        },
        indent=2,
    ).encode()

    project_digest = await create_digest(
        CreateDigest(
            [
                FileContent("package.json", package_json),
                FileContent(request.lockfile_name, request.lockfile_bytes),
            ]
        ),
        **implicitly(),
    )

    pkg_manager = PackageManager.from_string(
        f"{request.pkg_manager_name}@{request.pkg_manager_version}"
    )

    install_result = await fallible_to_exec_result_or_raise(
        **implicitly(
            NodeJSToolProcess(
                pkg_manager.name,
                pkg_manager.version,
                args=pkg_manager.immutable_install_args,
                description=f"Install {request.options_scope} dependencies from lockfile",
                input_digest=project_digest,
                output_directories=("node_modules",),
                timeout_seconds=request.timeout_seconds,
                extra_env=request.extra_env,
            )
        )
    )

    return _NodeJSBundledToolInstalled(digest=install_result.output_digest)


async def _run_tool_with_bundled_lockfile(
    request: NodeJSToolRequest, nodejs: NodeJS
) -> Process:
    pkg_manager_version = nodejs.package_managers.get(nodejs.package_manager)
    pkg_manager_and_version = nodejs.default_package_manager
    if pkg_manager_version is None or pkg_manager_and_version is None:
        raise ValueError(
            softwrap(
                f"""
                Version for {nodejs.package_manager} has to be configured
                in [{nodejs.options_scope}].package_managers when running
                the tool '{request.binary_name}' with a bundled lockfile.
                """
            )
        )
    pkg_manager = PackageManager.from_string(pkg_manager_and_version)

    if request.lockfile == DEFAULT_TOOL_LOCKFILE:
        if not request.default_lockfile_resources:
            raise ValueError(
                f"No default lockfile resources configured for tool '{request.options_scope}'."
            )
        if pkg_manager.name not in request.default_lockfile_resources:
            raise ValueError(
                softwrap(
                    f"""
                    No bundled lockfile for package manager '{pkg_manager.name}' in tool
                    '{request.options_scope}'. Available: {', '.join(request.default_lockfile_resources.keys())}.
                    """
                )
            )
        pkg, filename = request.default_lockfile_resources[pkg_manager.name]
        lockfile_bytes = importlib.resources.files(pkg).joinpath(filename).read_bytes()
    else:
        assert request.lockfile is not None
        user_lockfile = await read_nodejs_tool_user_lockfile(
            _NodeJSUserLockfileRequest(
                path=request.lockfile,
                description_of_origin=f"the option `[{request.options_scope}].lockfile`",
            )
        )
        lockfile_bytes = user_lockfile.content

    package_name, package_version = _parse_package_name_and_version(request.package)

    installed = await install_nodejs_tool_from_bundled_lockfile(
        _NodeJSBundledToolInstallRequest(
            pkg_manager_name=pkg_manager.name,
            pkg_manager_version=pkg_manager.version,
            lockfile_name=pkg_manager.lockfile_name,
            lockfile_bytes=lockfile_bytes,
            package_name=package_name,
            package_version=package_version,
            options_scope=request.options_scope,
            extra_env=FrozenDict(pkg_manager.extra_env),
            timeout_seconds=request.timeout_seconds,
        )
    )

    execution_input = await merge_digests(
        MergeDigests([request.input_digest, installed.digest])
    )

    # Invoke the binary from node_modules/.bin directly rather than via `npx`/`pnpm run` so the
    # immutable lockfile install isn't repeated.
    return await setup_node_tool_process(
        NodeJSToolProcess(
            f"node_modules/.bin/{request.binary_name}",
            tool_version=None,
            args=request.args,
            description=request.description,
            input_digest=execution_input,
            output_files=request.output_files,
            output_directories=request.output_directories,
            append_only_caches=request.append_only_caches,
            timeout_seconds=request.timeout_seconds,
            extra_env=FrozenDict({**pkg_manager.extra_env, **request.extra_env}),
        ),
        **implicitly(),
    )


async def _run_tool_without_resolve(request: NodeJSToolRequest, nodejs: NodeJS) -> Process:
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
async def prepare_tool_process(request: NodeJSToolRequest, nodejs: NodeJS) -> Process:
    if request.resolve is not None:
        return await _run_tool_with_resolve(request, request.resolve)
    if request.lockfile is not None:
        return await _run_tool_with_bundled_lockfile(request, nodejs)
    return await _run_tool_without_resolve(request, nodejs)


def rules() -> Iterable[Rule | UnionRule]:
    return [*collect_rules(), *nodejs_project_environment.rules(), *install_node_package.rules()]
