# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import os.path
from dataclasses import dataclass, replace
from pathlib import PurePath
from typing import Iterable

from pants.backend.javascript import package_json
from pants.backend.javascript.package_json import AllPackageJson, PackageJson
from pants.engine.collection import Collection
from pants.engine.rules import Rule, collect_rules, rule
from pants.engine.unions import UnionRule
from pants.util.ordered_set import FrozenOrderedSet
from pants.util.strutil import softwrap


@dataclass(frozen=True)
class NodeJSProject:
    root_dir: str
    workspaces: FrozenOrderedSet[PackageJson]

    def is_parent(self, project: NodeJSProject) -> bool:
        return self != project and any(
            project.root_dir == workspace.root_dir for workspace in self.workspaces
        )

    def including_workspaces_from(self, child: NodeJSProject) -> NodeJSProject:
        return replace(self, workspaces=self.workspaces | child.workspaces)


class AllNodeJSProjects(Collection[NodeJSProject]):
    pass


@dataclass(frozen=True)
class ProjectPaths:
    root: str
    project_globs: list[str]

    def full_globs(self) -> Iterable[str]:
        return (os.path.join(self.root, project) for project in self.project_globs)

    def matches_glob(self, pkg_json: PackageJson) -> bool:
        path = PurePath(pkg_json.root_dir)
        return any(path.match(glob) for glob in self.full_globs())


@rule
async def find_node_js_projects(all_package_json: AllPackageJson) -> AllNodeJSProjects:
    project_paths = (
        ProjectPaths(pkg.root_dir, ["", *(pkg.workspaces_ or ())]) for pkg in all_package_json
    )

    node_js_projects = {
        NodeJSProject(
            paths.root, FrozenOrderedSet(pkg for pkg in all_package_json if paths.matches_glob(pkg))
        )
        for paths in project_paths
    }
    return AllNodeJSProjects(_merge_workspaces(node_js_projects))


def _project_to_parents(
    projects: Iterable[NodeJSProject],
) -> dict[NodeJSProject, list[NodeJSProject]]:
    return {
        project: [
            candidate_parent for candidate_parent in projects if candidate_parent.is_parent(project)
        ]
        for project in projects
    }


def _merge_workspaces(node_js_projects: Iterable[NodeJSProject]) -> Iterable[NodeJSProject]:
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
