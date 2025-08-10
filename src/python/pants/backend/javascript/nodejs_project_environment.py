# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import os.path
from collections.abc import Iterable
from dataclasses import dataclass, field

from pants.backend.javascript import package_json, resolve
from pants.backend.javascript.nodejs_project import NodeJSProject
from pants.backend.javascript.package_json import (
    NodePackageExtraEnvVarsField,
    NodePackageNameField,
    OwningNodePackage,
    OwningNodePackageRequest,
    find_owning_package,
)
from pants.backend.javascript.resolve import (
    ChosenNodeResolve,
    RequestNodeResolve,
    resolve_for_package,
)
from pants.backend.javascript.subsystems import nodejs
from pants.backend.javascript.subsystems.nodejs import NodeJSToolProcess, setup_node_tool_process
from pants.build_graph.address import Address
from pants.engine.env_vars import EnvironmentVarsRequest
from pants.engine.internals.native_engine import EMPTY_DIGEST, Digest, MergeDigests
from pants.engine.internals.platform_rules import environment_vars_subset
from pants.engine.internals.selectors import concurrently
from pants.engine.intrinsics import merge_digests, path_globs_to_digest
from pants.engine.process import Process
from pants.engine.rules import Rule, collect_rules, implicitly, rule
from pants.engine.target import Target
from pants.engine.unions import UnionRule
from pants.util.dirutil import fast_relpath
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel


@dataclass(frozen=True)
class NodeJSProjectEnvironmentRequest:
    address: Address


@dataclass(frozen=True)
class NodeJsProjectEnvironment:
    resolve: ChosenNodeResolve
    package: OwningNodePackage | None = None

    @classmethod
    def from_root(cls, project: NodeJSProject) -> NodeJsProjectEnvironment:
        return cls(resolve=ChosenNodeResolve(project), package=None)

    @property
    def project(self) -> NodeJSProject:
        return self.resolve.project

    @property
    def root_dir(self) -> str:
        return self.project.root_dir

    @property
    def node_modules_directories(self) -> Iterable[str]:
        yield "node_modules"
        if self.package and not self.project.single_workspace:
            yield os.path.join(self.relative_workspace_directory(), "node_modules")

    @property
    def target(self) -> Target | None:
        if self.package:
            return self.package.target
        else:
            return None

    def package_dir(self) -> str:
        if self.package and not self.project.single_workspace:
            return self.ensure_target().residence_dir
        else:
            return self.root_dir

    def relative_workspace_directory(self) -> str:
        target = self.ensure_target()
        from_root_to_workspace = fast_relpath(target.residence_dir, self.root_dir)
        return from_root_to_workspace

    def ensure_target(self) -> Target:
        if self.target:
            return self.target
        raise ValueError("")


@dataclass(frozen=True)
class NodeJsProjectEnvironmentProcess:
    env: NodeJsProjectEnvironment
    args: Iterable[str]
    description: str
    level: LogLevel = LogLevel.INFO
    input_digest: Digest = EMPTY_DIGEST
    output_files: tuple[str, ...] = ()
    output_directories: tuple[str, ...] = ()
    per_package_caches: FrozenDict[str, str] = field(default_factory=FrozenDict)
    project_caches: FrozenDict[str, str] = field(default_factory=FrozenDict)
    timeout_seconds: int | None = None
    extra_env: FrozenDict[str, str] = field(default_factory=FrozenDict)

    def targeted_args(self) -> tuple[str, ...]:
        if (
            not self.env.project.single_workspace
            and self.env.target
            and self.env.root_dir != self.env.package_dir()
        ):
            target = self.env.ensure_target()
            return (
                self.env.project.workspace_specifier_arg,
                target[NodePackageNameField].value,
                *self.args,
            )
        else:
            return tuple(self.args)


@rule(desc="Assembling nodejs project environment")
async def get_nodejs_environment(req: NodeJSProjectEnvironmentRequest) -> NodeJsProjectEnvironment:
    node_resolve, owning_tgt = await concurrently(
        resolve_for_package(RequestNodeResolve(req.address), **implicitly()),
        find_owning_package(OwningNodePackageRequest(req.address)),
    )
    assert owning_tgt.target, f"Already ensured to exist by {ChosenNodeResolve.__name__}."

    return NodeJsProjectEnvironment(node_resolve, owning_tgt)


@rule
async def setup_nodejs_project_environment_process(
    req: NodeJsProjectEnvironmentProcess,
    nodejs: nodejs.NodeJS,
) -> Process:
    target_env_vars = (
        req.env.target.get(NodePackageExtraEnvVarsField).value or () if req.env.target else ()
    )

    lockfile_digest, project_digest, subsystem_env_vars, env_vars = await concurrently(
        path_globs_to_digest(req.env.resolve.get_lockfile_glob()),
        merge_digests(req.env.project.get_project_digest()),
        environment_vars_subset(EnvironmentVarsRequest(nodejs.extra_env_vars), **implicitly()),
        environment_vars_subset(EnvironmentVarsRequest(target_env_vars), **implicitly()),
    )
    merged = await merge_digests(MergeDigests((req.input_digest, lockfile_digest, project_digest)))

    args = req.targeted_args()
    output_files = req.output_files
    output_directories = req.output_directories
    per_package_caches = FrozenDict(
        {
            key: os.path.join(req.env.package_dir(), value)
            for key, value in req.per_package_caches.items()
        }
    )
    final_append_only_caches = FrozenDict(
        **per_package_caches, **req.project_caches, **req.env.project.extra_caches()
    )

    return await setup_node_tool_process(
        **implicitly(
            NodeJSToolProcess(
                tool=req.env.project.package_manager.name,
                tool_version=req.env.project.package_manager.version,
                args=args,
                description=req.description,
                level=req.level,
                input_digest=merged,
                working_directory=req.env.root_dir,
                output_files=output_files,
                output_directories=output_directories,
                append_only_caches=final_append_only_caches,
                timeout_seconds=req.timeout_seconds,
                project_digest=project_digest,
                extra_env=FrozenDict(
                    {
                        **subsystem_env_vars,
                        **env_vars,
                        **req.extra_env,
                        **req.env.project.extra_env(),
                    }
                ),
            )
        )
    )


def rules() -> Iterable[Rule | UnionRule]:
    return [*collect_rules(), *nodejs.rules(), *resolve.rules(), *package_json.rules()]
