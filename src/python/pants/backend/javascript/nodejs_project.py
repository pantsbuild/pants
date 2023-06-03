# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import itertools
import os.path
from dataclasses import dataclass, replace
from pathlib import PurePath
from typing import Iterable

from pants.backend.javascript import package_json
from pants.backend.javascript.package_json import (
    AllPackageJson,
    PackageJson,
    PnpmWorkspaceGlobs,
    PnpmWorkspaces,
)
from pants.backend.javascript.subsystems import nodejs
from pants.backend.javascript.subsystems.nodejs import NodeJS
from pants.core.util_rules import stripped_source_files
from pants.core.util_rules.stripped_source_files import StrippedFileName, StrippedFileNameRequest
from pants.engine.collection import Collection
from pants.engine.internals.native_engine import MergeDigests
from pants.engine.internals.selectors import Get
from pants.engine.rules import Rule, collect_rules, rule
from pants.engine.unions import UnionRule
from pants.util.ordered_set import FrozenOrderedSet
from pants.util.strutil import softwrap


@dataclass(frozen=True)
class _TentativeProject:
    root_dir: str
    workspaces: FrozenOrderedSet[PackageJson]
    default_resolve_name: str

    def is_parent(self, project: _TentativeProject) -> bool:
        return self.root_dir != project.root_dir and any(
            project.root_dir == workspace.root_dir for workspace in self.workspaces
        )

    def including_workspaces_from(self, child: _TentativeProject) -> _TentativeProject:
        return replace(self, workspaces=self.workspaces | child.workspaces)

    def root_workspace(self) -> PackageJson | None:
        for ws in self.workspaces:
            if ws.root_dir == self.root_dir:
                return ws
        return None


@dataclass(frozen=True)
class NodeJSProject:
    root_dir: str
    workspaces: FrozenOrderedSet[PackageJson]
    default_resolve_name: str
    package_manager: str
    package_manager_version: str | None = None
    pnpm_workspace: PnpmWorkspaceGlobs | None = None

    @property
    def lockfile_name(self) -> str:
        if self.package_manager == "pnpm":
            return "pnpm-lock.yaml"
        elif self.package_manager == "yarn":
            return "yarn.lock"
        return "package-lock.json"

    @property
    def generate_lockfile_args(self) -> tuple[str, ...]:
        if self.package_manager == "pnpm":
            return ("install", "--lockfile-only")
        elif self.package_manager == "yarn":
            return ("install",)  # yarn does not provide a lockfile only mode.
        return ("install", "--package-lock-only")

    @property
    def immutable_install_args(self) -> tuple[str, ...]:
        if self.package_manager == "npm":
            return ("clean-install",)
        return ("install", "--frozen-lockfile")

    @property
    def workspace_specifier_arg(self) -> str:
        if self.package_manager == "pnpm":
            return "--filter"
        elif self.package_manager == "yarn":
            return "workspace"
        return "--workspace"

    def extra_env(self) -> dict[str, str]:
        if self.package_manager == "pnpm":
            return {"PNPM_HOME": "{chroot}/._pnpm_home"}
        elif self.package_manager == "yarn":
            return {"YARN_CACHE_FOLDER": "{chroot}/._yarn_cache"}
        return {}

    @property
    def pack_archive_format(self) -> str:
        if self.package_manager == "yarn":
            return "{}-v{}.tgz"
        else:
            return "{}-{}.tgz"

    def extra_caches(self) -> dict[str, str]:
        if self.package_manager == "pnpm":
            return {"pnpm_home": "._pnpm_home"}
        elif self.package_manager == "yarn":
            return {"yarn_cache": "._yarn_cache"}
        return {}

    def get_project_digest(self) -> MergeDigests:
        return MergeDigests(
            itertools.chain(
                (ws.digest for ws in self.workspaces),
                [self.pnpm_workspace.digest] if self.pnpm_workspace else [],
            )
        )

    @property
    def single_workspace(self) -> bool:
        return len(self.workspaces) == 1 and next(iter(self.workspaces)).root_dir == self.root_dir

    @classmethod
    def from_tentative(
        cls, project: _TentativeProject, nodejs: NodeJS, pnpm_workspaces: PnpmWorkspaces
    ) -> NodeJSProject:
        root_ws = project.root_workspace()
        package_manager: str | None = None
        if root_ws:
            package_manager = root_ws.package_manager or nodejs.default_package_manager
        if not package_manager:
            raise ValueError(
                softwrap(
                    f"""
                    Could not determine package manager for project {project.default_resolve_name}.

                    Either configure a default [{NodeJS.name}].package_manager, or set the root
                    `package.json#packageManager` property.
                    """
                )
            )

        for workspace in project.workspaces:
            if workspace.package_manager:
                if not package_manager == workspace.package_manager:
                    ws_ref = f"{workspace.name}@{workspace.version}"
                    raise ValueError(
                        softwrap(
                            f"""
                            Workspace {ws_ref}'s package manager
                            {workspace.package_manager} is not compatible with
                            project {project.default_resolve_name}'s package manager {package_manager}.

                            Move or duplicate the `package.json#packageManager` entry from the
                            workspace {ws_ref} to the root package to resolve this error.
                            """
                        )
                    )
        package_manager_command, *maybe_version = package_manager.split("@")
        package_manager_version = maybe_version[0] if maybe_version else None

        return NodeJSProject(
            root_dir=project.root_dir,
            workspaces=project.workspaces,
            default_resolve_name=project.default_resolve_name,
            package_manager=package_manager_command,
            package_manager_version=package_manager_version,
            pnpm_workspace=pnpm_workspaces.for_root(project.root_dir),
        )


class AllNodeJSProjects(Collection[NodeJSProject]):
    def project_for_directory(self, directory: str) -> NodeJSProject:
        for project in self:
            if directory in (workspace.root_dir for workspace in project.workspaces):
                return project
        raise ValueError(
            f"{directory} is not a package directory that is part of a project. This is likely a bug."
        )


@dataclass(frozen=True)
class ProjectPaths:
    root: str
    project_globs: list[str]

    def full_globs(self) -> Iterable[str]:
        return (os.path.join(self.root, project) for project in self.project_globs)

    def matches_glob(self, pkg_json: PackageJson) -> bool:
        path = PurePath(pkg_json.root_dir)

        def safe_match(glob: str) -> bool:
            if glob == "":
                return pkg_json.root_dir == ""
            return path.match(glob)

        return any(safe_match(glob) for glob in self.full_globs())


async def _get_default_resolve_name(path: str) -> str:
    stripped = await Get(StrippedFileName, StrippedFileNameRequest(path))
    return stripped.value.replace(os.path.sep, ".")


@rule
async def find_node_js_projects(
    package_workspaces: AllPackageJson, pnpm_workspaces: PnpmWorkspaces, nodejs: NodeJS
) -> AllNodeJSProjects:
    project_paths = (
        ProjectPaths(pkg.root_dir, ["", *pkg.workspaces])
        if pkg not in pnpm_workspaces
        else ProjectPaths(pkg.root_dir, ["", *pnpm_workspaces[pkg].packages])
        for pkg in package_workspaces
    )

    node_js_projects = {
        _TentativeProject(
            paths.root,
            FrozenOrderedSet(pkg for pkg in package_workspaces if paths.matches_glob(pkg)),
            await _get_default_resolve_name(paths.root),
        )
        for paths in project_paths
    }
    merged_projects = _merge_workspaces(node_js_projects)
    return AllNodeJSProjects(
        NodeJSProject.from_tentative(p, nodejs, pnpm_workspaces) for p in merged_projects
    )


def _project_to_parents(
    projects: set[_TentativeProject],
) -> dict[_TentativeProject, list[_TentativeProject]]:
    return {
        project: [
            candidate_parent for candidate_parent in projects if candidate_parent.is_parent(project)
        ]
        for project in sorted(projects, key=lambda p: p.root_dir, reverse=False)
    }


def _merge_workspaces(node_js_projects: set[_TentativeProject]) -> Iterable[_TentativeProject]:
    project_to_parents = _project_to_parents(node_js_projects)
    while any(parents for parents in project_to_parents.values()):
        _ensure_one_parent(project_to_parents)
        node_js_projects = set()
        for project, parents in project_to_parents.items():
            node_js_projects -= {project, *parents}
            node_js_projects.add(
                parents[0].including_workspaces_from(project) if parents else project
            )
        project_to_parents = _project_to_parents(node_js_projects)
    return node_js_projects


def _ensure_one_parent(
    project_to_parents: dict[_TentativeProject, list[_TentativeProject]]
) -> None:
    for project, parents in project_to_parents.items():
        if len(parents) > 1:
            raise ValueError(
                softwrap(
                    f"""
                    Nodejs projects {', '.join(parent.root_dir for parent in parents)}
                    are specifying {project.root_dir} to be part of their workspaces.

                    A package can only be part of one project.
                    """
                )
            )


def rules() -> Iterable[Rule | UnionRule]:
    return [
        *nodejs.rules(),
        *package_json.rules(),
        *stripped_source_files.rules(),
        *collect_rules(),
    ]
