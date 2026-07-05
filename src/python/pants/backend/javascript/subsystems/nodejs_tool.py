# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import importlib.resources
import json
import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import ClassVar

import nodesemver

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
from pants.core.goals.generate_lockfiles import DEFAULT_TOOL_LOCKFILE
from pants.core.goals.resolves import ExportableTool
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
from pants.option.option_types import StrOption
from pants.option.subsystem import Subsystem
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.ordered_set import OrderedSet
from pants.util.strutil import softwrap

logger = logging.getLogger(__name__)

# Tool (scope, version) pairs we've already warned about ignoring their bundled lockfile, so a
# version override doesn't emit the warning on every `fmt`/`lint`/`check` invocation. Keyed by the
# version too, so changing the override within a long-lived `pantsd` re-emits the warning.
_warned_bundled_lockfile_ignored: OrderedSet[tuple[str, str]] = OrderedSet()


class NodeJSToolBase(Subsystem, ExportableTool):
    # Subclasses must set.
    default_version: ClassVar[str]

    # Tools that ship a bundled lockfile opt in, e.g.
    #   default_lockfile_resources = bundled_lockfiles(__package__, "prettier")
    default_lockfile_resources: ClassVar[dict[str, tuple[str, str]] | None] = None

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
            file path, that lockfile will be used instead. If unset or set to the
            empty string, no lockfile will be used and the tool will be installed
            without pinned transitive dependencies.

            The bundled lockfile pins the dependency tree of the default `version`. If you
            override `version`, the bundled lockfile is ignored and the tool runs without
            pinned transitive dependencies; set this option to a path and run
            `generate-lockfiles` to pin a custom version.
            """
        ),
    )

    @property
    def binary_name(self) -> str:
        if self._binary_name:
            return self._binary_name

        package_name, _ = _split_package_spec(self.version)
        if package_name.startswith("@"):
            # Scoped packages (`@scope/name`) conventionally expose a binary named after the scope,
            # e.g. `@redocly/cli` → `redocly`. A scoped spec must have both a scope and a name.
            scope, sep, name = package_name[1:].partition("/")
            if not sep or not scope or not name:
                raise ValueError(f"Invalid npm package specification: {self.version}")
            return scope
        if not package_name:
            raise ValueError(f"Invalid npm package specification: {self.version}")
        return package_name

    install_from_resolve = StrOption(
        advanced=True,
        default=None,
        help=lambda cls: softwrap(
            f"""\
            If specified, install the tool using the lockfile for this named resolve,
            instead of the version configured in this subsystem.

            If unspecified, the tool will use the default configured package manager
            `[{NodeJS.options_scope}].package_manager`, and install the tool without a
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
        lockfile = self.lockfile or None
        if lockfile == DEFAULT_TOOL_LOCKFILE and self.version != self.default_version:
            # The bundled lockfile pins the default version's dependency tree; an immutable
            # install of an overridden version against it would fail as out-of-sync. Fall back
            # to unpinned execution, matching pre-lockfile behavior for version overrides.
            warn_key = (self.options_scope, self.version)
            if warn_key not in _warned_bundled_lockfile_ignored:
                _warned_bundled_lockfile_ignored.add(warn_key)
                logger.warning(
                    f"`[{self.options_scope}].version` is set to {self.version}, which differs "
                    f"from the default {self.default_version} that the bundled lockfile pins. "
                    f"Ignoring the bundled lockfile and installing {self.options_scope} without "
                    f"pinned transitive dependencies. To pin them, set "
                    f"`[{self.options_scope}].lockfile` to a path and run "
                    f"`generate-lockfiles --resolve={self.options_scope}`."
                )
            lockfile = None
        return NodeJSToolRequest(
            package=self.version,
            binary_name=self.binary_name,
            resolve=self.install_from_resolve,
            lockfile=lockfile,
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

    @classmethod
    def help_for_generate_lockfile_with_default_location(cls, resolve_name: str):
        return softwrap(
            f"""
            You requested to generate a lockfile for {resolve_name}, but it is configured to
            use its bundled lockfile. To generate a custom lockfile, set
            `[{resolve_name}].lockfile` to the path where it should be written, then rerun
            `generate-lockfiles --resolve={resolve_name}`.
            """
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
    lockfile: str | None = None
    default_lockfile_resources: FrozenDict[str, tuple[str, str]] | None = None


def _split_package_spec(package: str) -> tuple[str, str | None]:
    """Split `name[@version]` or `@scope/name[@version]` into (name, version_or_None).

    Scoped packages (leading `@`) have their version separator at the second `@`, not the first.
    """
    search_start = 1 if package.startswith("@") else 0
    at_idx = package.find("@", search_start)
    if at_idx == -1:
        return package, None
    return package[:at_idx], package[at_idx + 1 :]


def _parse_package_name_and_version(package: str) -> tuple[str, str]:
    name, version = _split_package_spec(package)
    if not name or not version:
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


def bundled_lockfiles(package: str, prefix: str) -> dict[str, tuple[str, str]]:
    """Build a `NodeJSToolBase.default_lockfile_resources` dict for a tool that ships lockfiles for
    npm/yarn/pnpm at `{prefix}.{pm.lockfile_name}` within `package`.

    Example:
        default_lockfile_resources = bundled_lockfiles(__package__, "prettier")
    """
    pms = (PackageManager.npm(None), PackageManager.yarn(None), PackageManager.pnpm(None))
    return {pm.name: (package, f"{prefix}.{pm.lockfile_name}") for pm in pms}


def _active_package_manager(
    nodejs: NodeJS, purpose: str, install_from_resolve_scope: str | None = None
) -> PackageManager:
    default_package_manager = nodejs.default_package_manager
    if (
        nodejs.package_managers.get(nodejs.package_manager) is None
        or default_package_manager is None
    ):
        hint = (
            f" Alternatively, set `[{install_from_resolve_scope}].install_from_resolve` to install"
            " the tool using the lockfile of a named resolve."
            if install_from_resolve_scope
            else ""
        )
        raise ValueError(
            softwrap(
                f"""
                A version for {nodejs.package_manager} must be configured in
                [{nodejs.options_scope}].package_managers {purpose}.{hint}
                """
            )
        )
    return PackageManager.from_string(default_package_manager)


def _ensure_bundled_lockfile_supported(pkg_manager: PackageManager, options_scope: str) -> None:
    """The bundled/pinned-lockfile path execs `node_modules/.bin/<tool>` directly and ships Yarn
    Classic-format `yarn.lock`s. Yarn Berry (v2+) defaults to the Plug'n'Play linker, which produces
    no `node_modules/.bin`, so the path cannot work with it. Fail with an actionable error rather
    than an opaque missing-binary / lockfile-format error at install or exec time.
    """
    if (
        pkg_manager.name == "yarn"
        and pkg_manager.version is not None
        and not nodesemver.satisfies(pkg_manager.version, "1.x")
    ):
        raise ValueError(
            softwrap(
                f"""
                `yarn@{pkg_manager.version}` (Yarn Berry) is not supported for {options_scope}'s
                pinned lockfile: Berry uses the Plug'n'Play linker (no `node_modules/.bin`, which
                this install path requires) and the lockfiles are Yarn Classic format. Pin
                `[{NodeJS.options_scope}].package_managers` to a Yarn 1.x version, use npm or pnpm,
                or set `[{options_scope}].install_from_resolve` to install from a named resolve.
                """
            )
        )


def _nodejs_pm_process(
    pkg_manager: PackageManager,
    *,
    args: tuple[str, ...],
    description: str,
    input_digest: Digest,
    output_files: tuple[str, ...] = (),
    output_directories: tuple[str, ...] = (),
    append_only_caches: FrozenDict[str, str] = FrozenDict(),
) -> NodeJSToolProcess:
    """Build a `NodeJSToolProcess` invoking `pkg_manager` pinned to its configured version with the
    package manager's cache env applied. Shared by the immutable-install and lockfile-generation
    paths so version pinning and cache env stay consistent between them.
    """
    return NodeJSToolProcess(
        pkg_manager.name,
        pkg_manager.version,
        args=args,
        description=description,
        input_digest=input_digest,
        output_files=output_files,
        output_directories=output_directories,
        append_only_caches=append_only_caches,
        extra_env=FrozenDict(pkg_manager.extra_env),
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
    if len(contents) != 1:
        raise ValueError(
            softwrap(
                f"""
                The path from {request.description_of_origin} must match exactly one lockfile,
                but matched {len(contents)} files: {", ".join(c.path for c in contents)}.
                """
            )
        )
    return _NodeJSLockfileContents(contents[0].content)


@dataclass(frozen=True)
class _NodeJSBundledLockfileRequest:
    package: str
    filename: str


@rule
async def read_nodejs_tool_bundled_lockfile(
    request: _NodeJSBundledLockfileRequest,
) -> _NodeJSLockfileContents:
    # Bundled lockfiles ship as package resources; `importlib.resources` reads them whether Pants
    # runs from a source tree, an installed wheel, or a zipped PEX. Isolating the read in its own
    # rule memoizes it per (package, filename) rather than repeating it on every tool invocation.
    # The bytes are treated as immutable within a released Pants version (they change only on
    # regeneration, which runs in a fresh buildroot), so the read intentionally isn't engine-tracked.
    return _NodeJSLockfileContents(
        importlib.resources.files(request.package).joinpath(request.filename).read_bytes()
    )


@dataclass(frozen=True)
class _NodeJSBundledToolInstallRequest:
    package_manager: PackageManager
    lockfile_bytes: bytes
    package_name: str
    package_version: str
    options_scope: str


@rule
async def install_nodejs_tool_from_bundled_lockfile(
    request: _NodeJSBundledToolInstallRequest,
) -> Digest:
    pkg_manager = request.package_manager
    project_digest = await create_digest(
        CreateDigest(
            [
                FileContent(
                    "package.json",
                    _tool_package_json_bytes(
                        request.options_scope, request.package_name, request.package_version
                    ),
                ),
                FileContent(pkg_manager.lockfile_name, request.lockfile_bytes),
            ]
        ),
        **implicitly(),
    )

    install_result = await fallible_to_exec_result_or_raise(
        **implicitly(
            _nodejs_pm_process(
                pkg_manager,
                args=pkg_manager.immutable_install_args,
                description=f"Install {request.options_scope} dependencies from lockfile",
                input_digest=project_digest,
                output_directories=("node_modules",),
                # Persist the package manager's store/cache (pnpm_home, yarn_cache) across runs so a
                # cold install doesn't re-download the whole dependency tree, matching the resolve
                # path. npm's cache is added by `setup_node_tool_process` via the environment.
                append_only_caches=pkg_manager.extra_caches,
                # No timeout: this is a one-time, cached dependency fetch. A caller's
                # `timeout_seconds` bounds the tool run, not this hidden install step.
            )
        )
    )

    return install_result.output_digest


@dataclass(frozen=True)
class _NodeJSBundledToolProcessRequest:
    request: NodeJSToolRequest


@rule
async def prepare_tool_process_with_bundled_lockfile(
    bundled: _NodeJSBundledToolProcessRequest, nodejs: NodeJS
) -> Process:
    request = bundled.request
    assert request.lockfile is not None
    pkg_manager = _active_package_manager(
        nodejs, f"to run the tool '{request.binary_name}'", request.options_scope
    )
    _ensure_bundled_lockfile_supported(pkg_manager, request.options_scope)

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
                    '{request.options_scope}'. Available: {", ".join(request.default_lockfile_resources.keys())}.
                    """
                )
            )
        pkg, filename = request.default_lockfile_resources[pkg_manager.name]
        lockfile = await read_nodejs_tool_bundled_lockfile(
            _NodeJSBundledLockfileRequest(package=pkg, filename=filename)
        )
    else:
        lockfile = await read_nodejs_tool_user_lockfile(
            _NodeJSUserLockfileRequest(
                path=request.lockfile,
                description_of_origin=f"the option `[{request.options_scope}].lockfile`",
            )
        )

    package_name, package_version = _parse_package_name_and_version(request.package)

    installed_digest = await install_nodejs_tool_from_bundled_lockfile(
        _NodeJSBundledToolInstallRequest(
            package_manager=pkg_manager,
            lockfile_bytes=lockfile.content,
            package_name=package_name,
            package_version=package_version,
            options_scope=request.options_scope,
        )
    )

    execution_input = await merge_digests(MergeDigests([request.input_digest, installed_digest]))

    # The immutable install above already placed the pinned binary at
    # `node_modules/.bin/{binary_name}`, so run it directly. Going through the package manager
    # instead (`npx`/`pnpm dlx`, or `<pm> exec`) would re-resolve or reinstall the dependency
    # tree we just pinned. `setup_node_tool_process` execs a non-package-manager `tool` as
    # argv[0] as-is; the process runs with the sandbox root as its working directory (so the
    # relative path resolves) and always has the node binary directory on PATH (so the
    # `#!/usr/bin/env node` shebang resolves).
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
    pkg_manager = _active_package_manager(
        nodejs, f"to run the tool '{request.binary_name}'", request.options_scope
    )

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
        # Any configured package manager is allowed to consume the lockfile. A compatible
        # version installs against it (preserving pinning); a genuinely incompatible one
        # (e.g. Yarn Berry vs a v1 yarn.lock) fails the immutable install loudly, which is
        # more honest than silently dropping the lockfile.
        return await prepare_tool_process_with_bundled_lockfile(
            _NodeJSBundledToolProcessRequest(request), **implicitly()
        )
    return await _run_tool_without_resolve(request, nodejs)


def rules() -> Iterable[Rule | UnionRule]:
    return [*collect_rules(), *nodejs_project_environment.rules(), *install_node_package.rules()]


def rules_for_tool(tool_cls: type[NodeJSToolBase]) -> Iterable[Rule | UnionRule]:
    """All rules needed to register a NodeJSToolBase subsystem in its backend's `rules()`."""
    return [*rules(), UnionRule(ExportableTool, tool_cls)]
