# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import os.path
from dataclasses import dataclass, replace
from pathlib import PurePath
from typing import Iterable

from pants.backend.javascript import package_json
from pants.backend.javascript.package_json import AllPackageJson, PackageJson
from pants.engine.collection import Collection, DeduplicatedCollection
from pants.engine.internals.native_engine import Digest, MergeDigests
from pants.engine.rules import Rule, collect_rules, rule
from pants.engine.unions import UnionRule
from pants.util.ordered_set import FrozenOrderedSet
from pants.util.strutil import softwrap


@dataclass(frozen=True)
class PackageJsonWorkspace:
    """Exists to not invalidate AllNodeJsProjects when irrelevant parts of PackageJson has
    changed."""

    name: str
    root_dir: str
    digest: Digest
    workspaces: tuple[str, ...]

    @classmethod
    def from_package_json(cls, pkg_json: PackageJson) -> PackageJsonWorkspace:
        return PackageJsonWorkspace(
            name=pkg_json.name,
            root_dir=pkg_json.root_dir,
            digest=pkg_json.digest,
            workspaces=pkg_json.workspaces,
        )


class PackageJsonWorkspaces(DeduplicatedCollection[PackageJsonWorkspace]):
    pass


@dataclass(frozen=True)
class NodeJSProject:
    root_dir: str
    workspaces: FrozenOrderedSet[PackageJsonWorkspace]

    def is_parent(self, project: NodeJSProject) -> bool:
        return self.root_dir != project.root_dir and any(
            project.root_dir == workspace.root_dir for workspace in self.workspaces
        )

    def including_workspaces_from(self, child: NodeJSProject) -> NodeJSProject:
        return replace(self, workspaces=self.workspaces | child.workspaces)

    @property
    def resolve_name(self) -> str:
        return self.root_dir.replace(os.path.sep, ".")

    def get_project_digest(self) -> MergeDigests:
        return MergeDigests(ws.digest for ws in self.workspaces)

    @property
    def single_workspace(self) -> bool:
        return len(self.workspaces) == 1 and next(iter(self.workspaces)).root_dir == self.root_dir


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

    def matches_glob(self, pkg_json: PackageJsonWorkspace) -> bool:
        path = PurePath(pkg_json.root_dir)
        return any(path.match(glob) for glob in self.full_globs())


@rule
async def parse_workspaces_from_package_json(
    all_package_json: AllPackageJson,
) -> PackageJsonWorkspaces:
    return PackageJsonWorkspaces(
        PackageJsonWorkspace.from_package_json(pkg_json) for pkg_json in all_package_json
    )


@rule
async def find_node_js_projects(package_workspaces: PackageJsonWorkspaces) -> AllNodeJSProjects:
    project_paths = (
        ProjectPaths(pkg.root_dir, ["", *pkg.workspaces]) for pkg in package_workspaces
    )

    node_js_projects = {
        NodeJSProject(
            paths.root,
            FrozenOrderedSet(pkg for pkg in package_workspaces if paths.matches_glob(pkg)),
        )
        for paths in project_paths
    }
    return AllNodeJSProjects(_merge_workspaces(node_js_projects))


def _project_to_parents(
    projects: set[NodeJSProject],
) -> dict[NodeJSProject, list[NodeJSProject]]:
    return {
        project: [
            candidate_parent for candidate_parent in projects if candidate_parent.is_parent(project)
        ]
        for project in sorted(projects, key=lambda p: p.root_dir, reverse=False)
    }


def _merge_workspaces(node_js_projects: set[NodeJSProject]) -> Iterable[NodeJSProject]:
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


def _ensure_one_parent(project_to_parents: dict[NodeJSProject, list[NodeJSProject]]) -> None:
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
    return [*package_json.rules(), *collect_rules()]
