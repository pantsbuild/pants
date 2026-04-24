# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import importlib.resources
import json
import os.path
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
        if self._binary_name:
            return self._binary_name

        package_name, _ = _split_package_spec(self.version)
        if not package_name:
            raise ValueError(f"Invalid npm package specification: {self.version}")
        if package_name.startswith("@"):
            # Scoped packages (`@scope/name`) conventionally expose a binary named after the scope,
            # e.g. `@redocly/cli` → `redocly`.
            return package_name[1:].split("/", 1)[0]
        return package_name

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

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        # If a tool subsystem didn't set `default_lockfile_resources` explicitly, derive it by
        # convention from the subsystem's own module and `options_scope`. Tools that don't ship
        # bundled lockfiles opt out with `lockfile_required = False` (e.g. TypeScript).
        if cls.lockfile_required and cls.default_lockfile_resources is None:
            cls.default_lockfile_resources = bundled_lockfiles(
                cls.__module__.rsplit(".", 1)[0], cls.options_scope
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


def _split_package_spec(package: str) -> tuple[str, str | None]:
    """Split `name[@version]` or `@scope/name[@version]` into (name, version_or_None).

    Scoped packages (leading `@`) have their version separator at the second `@`, not the first.
    """
    # Skip the leading `@` for scoped packages so we find the version separator (the second `@`).
    search_start = 1 if package.startswith("@") else 0
    at_idx = package.find("@", search_start)
    if at_idx == -1:
        return package, None
    return package[:at_idx], package[at_idx + 1 :]


def _parse_package_name_and_version(package: str) -> tuple[str, str]:
    name, version = _split_package_spec(package)
    if not name or version is None:
        raise ValueError(
            f"Invalid npm package specification '{package}': expected format 'package@version' "
            f"or '@scope/package@version'."
        )
    return name, version


def _tool_package_json_bytes(resolve_name: str, package_name: str, package_version: str) -> bytes:
    return json.dumps(
        {
            "name": f"pants-tool-{resolve_name}",
            "private": True,
            "dependencies": {package_name: package_version},
        },
        indent=2,
    ).encode()


def _lockfile_dest_for_resource(resource_pkg: str, filename: str) -> str:
    """In-repo path for a bundled lockfile resource, relative to the buildroot."""
    return os.path.join("src", "python", resource_pkg.replace(".", os.path.sep), filename)


def bundled_lockfiles(package: str, prefix: str) -> dict[str, tuple[str, str]]:
    """Build a `NodeJSToolBase.default_lockfile_resources` dict for a tool that ships lockfiles for
    npm/yarn/pnpm at `{prefix}.{pm.lockfile_name}` within `package`.

    Example:
        default_lockfile_resources = bundled_lockfiles(__package__, "prettier")
    """
    pms = (PackageManager.npm(None), PackageManager.yarn(None), PackageManager.pnpm(None))
    return {pm.name: (package, f"{prefix}.{pm.lockfile_name}") for pm in pms}


def _active_package_manager(nodejs: NodeJS, for_tool: str) -> PackageManager:
    default_package_manager = nodejs.default_package_manager
    if (
        nodejs.package_managers.get(nodejs.package_manager) is None
        or default_package_manager is None
    ):
        raise ValueError(
            softwrap(
                f"""
                Version for {nodejs.package_manager} has to be configured
                in [{nodejs.options_scope}].package_managers to run the tool '{for_tool}'.
                """
            )
        )
    return PackageManager.from_string(default_package_manager)


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
    project_digest = await create_digest(
        CreateDigest(
            [
                FileContent(
                    "package.json",
                    _tool_package_json_bytes(
                        request.options_scope, request.package_name, request.package_version
                    ),
                ),
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
    pkg_manager = _active_package_manager(nodejs, request.binary_name)

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
    # Corepack requires a configured version in [nodejs].package_managers to pick a
    # "good known release"; there's no project package.json here to derive it from.
    pkg_manager = _active_package_manager(nodejs, request.binary_name)

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


def rules_for_tool(tool_cls: type[NodeJSToolBase]) -> Iterable[Rule | UnionRule]:
    """All rules needed to register a NodeJSToolBase subsystem in its backend's `rules()`."""
    return [*rules(), UnionRule(ExportableTool, tool_cls)]
