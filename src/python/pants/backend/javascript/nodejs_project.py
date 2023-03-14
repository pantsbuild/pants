# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import os.path
from dataclasses import dataclass, replace
from pathlib import PurePath
from typing import Iterable

from pants.backend.javascript import package_json
from pants.backend.javascript.package_json import AllPackageJson, PackageJson
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
class NodeJSProject:
    root_dir: str
    workspaces: FrozenOrderedSet[PackageJson]
    default_resolve_name: str

    def is_parent(self, project: NodeJSProject) -> bool:
        return self.root_dir != project.root_dir and any(
            project.root_dir == workspace.root_dir for workspace in self.workspaces
        )

    def including_workspaces_from(self, child: NodeJSProject) -> NodeJSProject:
        return replace(self, workspaces=self.workspaces | child.workspaces)

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

    def matches_glob(self, pkg_json: PackageJson) -> bool:
        path = PurePath(pkg_json.root_dir)
        return any(path.match(glob) for glob in self.full_globs())


async def _get_default_resolve_name(path: str) -> str:
    stripped = await Get(StrippedFileName, StrippedFileNameRequest(path))
    return stripped.value.replace(os.path.sep, ".")


@rule
async def find_node_js_projects(package_workspaces: AllPackageJson) -> AllNodeJSProjects:
    project_paths = (
        ProjectPaths(pkg.root_dir, ["", *pkg.workspaces]) for pkg in package_workspaces
    )

    node_js_projects = {
        NodeJSProject(
            paths.root,
            FrozenOrderedSet(pkg for pkg in package_workspaces if paths.matches_glob(pkg)),
            await _get_default_resolve_name(paths.root),
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
    return [*package_json.rules(), *stripped_source_files.rules(), *collect_rules()]
