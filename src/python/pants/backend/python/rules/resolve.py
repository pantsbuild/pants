# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import os
import re
from collections import defaultdict
from dataclasses import dataclass
from io import StringIO
from typing import Any, DefaultDict, Dict, List, Optional, Tuple, cast

from pants.backend.python.rules.download_pex_bin import PexBin
from pants.backend.python.rules.inject_init import InitInjectedSnapshot, InjectInitRequest
from pants.backend.python.rules.pex import Pex, PexDebug, PexRequest, PexRequirements
from pants.backend.python.rules.pex_tools.common import DistributionDependencies
from pants.backend.python.rules.pex_tools.pex_tool import PexTool
from pants.backend.python.subsystems.subprocess_environment import SubprocessEncodingEnvironment
from pants.backend.python.target_types import (
    PythonLibrary,
    PythonRequirementLibrary,
    PythonRequirementsField,
)
from pants.core.util_rules.distdir import DistDir
from pants.engine.addresses import Addresses
from pants.engine.console import Console
from pants.engine.fs import (
    EMPTY_SNAPSHOT,
    Digest,
    DirectoryToMaterialize,
    InputFilesContent,
    MergeDigests,
    PathGlobs,
    Snapshot,
    SnapshotSubset,
    Workspace,
)
from pants.engine.goal import Goal, GoalSubsystem, Outputting
from pants.engine.process import Process, ProcessResult
from pants.engine.rules import goal_rule, named_rule, rule
from pants.engine.selectors import Get, MultiGet
from pants.engine.target import Dependencies, Targets, TransitiveTargets
from pants.option.custom_types import GlobExpansionConjunction
from pants.option.global_options import GlobMatchErrorBehavior
from pants.python.python_repos import PythonRepos
from pants.python.python_setup import PythonSetup
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize


@dataclass(frozen=True)
class Resolver(PexTool):
    _entry_point = "resolver:main"
    _module_names = ("resolver", "common")

    pex: Pex


@named_rule(desc="Create python resolver")
async def create_resolver(pex_bin: PexBin) -> Resolver:
    resolver_snapshot = await Get[Snapshot](InputFilesContent, Resolver.files())
    init_injected = await Get[InitInjectedSnapshot](InjectInitRequest(snapshot=resolver_snapshot))
    return Resolver(
        pex=await Get[Pex](
            PexRequest(
                output_filename="bin/resolver.pex",
                requirements=PexRequirements((pex_bin.requirement, "dataclasses==0.6")),
                sources=init_injected.snapshot.digest,
                entry_point=Resolver.entry_point(),
                additional_args=("--no-strip-pex-env", "--unzip"),
            )
        )
    )


@dataclass(frozen=True)
class PexCache:
    snapshot: Snapshot = EMPTY_SNAPSHOT
    path: str = "pex_root"


@dataclass(frozen=True)
class ResolveRequest:
    requirements: PexRequirements
    cache: PexCache = PexCache()
    local: bool = False
    requirer: Optional[str] = None


@dataclass(frozen=True)
class ResolveResult:
    dependencies: DistributionDependencies = DistributionDependencies()
    cache: PexCache = PexCache()


@named_rule(desc="Resolve python requirements")
async def resolve_requirements(
    resolver: Resolver,
    python_setup: PythonSetup,
    python_repos: PythonRepos,
    request: ResolveRequest,
    subprocess_encoding_environment: SubprocessEncodingEnvironment,
    log_level: LogLevel,
) -> ResolveResult:
    argv = list(PexDebug(log_level).iter_pex_args())

    if python_setup.requirement_constraints is not None:
        constraint_file_snapshot = await Get[Snapshot](
            PathGlobs(
                [python_setup.requirement_constraints],
                glob_match_error_behavior=GlobMatchErrorBehavior.error,
                conjunction=GlobExpansionConjunction.all_match,
                description_of_origin="the option `--python-setup-requirement-constraints`",
            )
        )
        argv.extend(["--constraints", python_setup.requirement_constraints])
    else:
        constraint_file_snapshot = EMPTY_SNAPSHOT

    for interpreter_search_path in python_setup.interpreter_search_paths:
        argv.extend(["--interpreter-search-path", interpreter_search_path])

    for interpreter_constraint in python_setup.interpreter_constraints:
        argv.extend(["--interpreter-constraint", interpreter_constraint])

    if python_setup.resolver_jobs:
        argv.extend(["--jobs", python_setup.resolver_jobs])

    if python_setup.manylinux:
        argv.extend(["--manylinux", python_setup.manylinux])
    else:
        argv.append("--no-manylinux")

    if python_setup.resolver_allow_prereleases:
        argv.append("--pre")

    for platform in python_setup.platforms:
        argv.extend(["--platform", platform])

    if python_repos.indexes:
        for index in python_repos.indexes:
            argv.extend(["--index", index])
    else:
        argv.extend("--no-index")

    for repo in python_repos.repos:
        argv.extend(["--repo", repo])

    if request.local:
        argv.append("--single-interpreter")

    argv.extend(["--cache", request.cache.path])
    argv.extend(["--dest", os.path.join(request.cache.path, "resolved_dists")])

    argv.extend(["--", *request.requirements])

    resolve_input_files = await Get[Digest](
        MergeDigests(
            digests=(
                resolver.pex.digest,
                request.cache.snapshot.digest,
                constraint_file_snapshot.digest,
            )
        )
    )

    execute_resolve = resolver.pex.create_process(
        python_setup=python_setup,
        subprocess_encoding_environment=subprocess_encoding_environment,
        pex_path=resolver.pex.output_filename,
        pex_args=argv,
        input_digest=resolve_input_files,
        description=(
            f"Resolving {pluralize(len(request.requirements), 'requirement')}"
            f"{f' for {request.requirer}' if request.requirer else ''}: "
            f"{', '.join(request.requirements)}"
        ),
        output_directories=(request.cache.path,),
    )
    resolve_result = await Get[ProcessResult](Process, execute_resolve)
    dependencies = DistributionDependencies.load(StringIO(resolve_result.stdout.decode()))
    cache_snapshot = await Get[Snapshot](
        SnapshotSubset(
            digest=resolve_result.output_digest,
            globs=PathGlobs(
                globs=[
                    f"{request.cache.path}/**/*",
                    # Since we do not attempt to leverage https://www.python.org/dev/peps/pep-0552/,
                    # always discard bytecode cache files since they will contain a nondeterministic
                    # timestamp.
                    f"!{request.cache.path}/**/*.pyc",
                    f"!{request.cache.path}/**/__pycache__",
                ]
            ),
        )
    )
    return ResolveResult(dependencies=dependencies, cache=PexCache(snapshot=cache_snapshot))


class ResolveOptions(Outputting, GoalSubsystem):
    """Resolve python requirements."""

    name = "resolve"

    @classmethod
    def register_options(cls, register) -> None:
        super().register_options(register)
        register(
            "--local",
            type=bool,
            default=False,
            help="Just resolve for a single local interpreter that matches compatibility "
            "constraints, if any.",
        )

    @property
    def local(self) -> bool:
        return cast(bool, self.values.local)


@rule
async def resolve_target(options: ResolveOptions, target: PythonLibrary) -> ResolveResult:
    # Recurse to get the resolution cache, if any.
    direct_dependency_addresses = target[Dependencies].value
    if not direct_dependency_addresses:
        return ResolveResult()

    requests: List[Get[Any]] = [
        Get[Targets](Addresses(direct_dependency_addresses)),
        Get[TransitiveTargets](Addresses([target.address])),
    ]

    (direct_dependencies, transitive_dependencies) = cast(
        Tuple[Targets, TransitiveTargets], await MultiGet(requests)
    )

    requirements = tuple(
        str(requirement.requirement)
        for target in transitive_dependencies.closure
        if isinstance(target, PythonRequirementLibrary)
        for requirement in target[PythonRequirementsField].value
    )
    if not requirements:
        return ResolveResult()

    resolved_dependencies = await MultiGet(
        Get[ResolveResult](PythonLibrary, dependency)
        for dependency in direct_dependencies
        if isinstance(dependency, PythonLibrary)
    )

    # The Pip http cache is non-deterministic. It records HTTP headers from responses which
    # includes things like:
    #
    #   Date: Fri, 01 May 2020 17:20:41 GMT
    #
    # The non-determinism in these headers does not affect resolves, so we pick one winner when we
    # find duplicates to ensure we can merge caches without conflict.

    resolve_results_by_path: DefaultDict[str, List[ResolveResult]] = defaultdict(list)
    globs_by_resolve_result: DefaultDict[ResolveResult, List[str]] = defaultdict(list)

    for resolved_dependency in resolved_dependencies:
        # Include everything in the cache by default.
        globs_by_resolve_result[resolved_dependency].append(
            f"{resolved_dependency.cache.path}/**/*"
        )
        # But flag any files under http/ as potential conflicts since we know the Pip HTTP cache
        # has non-deterministic headers.
        potential_conflict = re.compile(rf"{resolved_dependency.cache.path}/http/")
        for path in resolved_dependency.cache.snapshot.files:
            if potential_conflict.match(path):
                resolve_results_by_path[path].append(resolved_dependency)

    potential_conflicts: Dict[str, List[ResolveResult]] = {
        path: results[1:] for path, results in resolve_results_by_path.items() if len(results) > 1
    }
    for path, resolve_results in potential_conflicts.items():
        for resolve_result in resolve_results:
            globs_by_resolve_result[resolve_result].append(f"!{path}")

    mergeable_caches = await MultiGet(
        Get[Snapshot](
            SnapshotSubset(
                digest=resolved_dependency.cache.snapshot.digest,
                globs=PathGlobs(globs=globs_by_resolve_result[resolved_dependency]),
            )
        )
        for resolved_dependency in resolved_dependencies
    )
    merged_cache_snapshot = await Get[Snapshot](
        MergeDigests(digests=tuple(mergeable_cache.digest for mergeable_cache in mergeable_caches))
    )

    return await Get[ResolveResult](
        ResolveRequest(
            requirer=target.address.spec,
            requirements=PexRequirements(
                tuple(
                    str(requirement.requirement)
                    for target in transitive_dependencies.closure
                    if isinstance(target, PythonRequirementLibrary)
                    for requirement in target[PythonRequirementsField].value
                )
            ),
            cache=PexCache(snapshot=merged_cache_snapshot),
            local=options.local,
        )
    )


class ResolveGoal(Goal):
    """Resolves third party dependencies for a target."""

    subsystem_cls = ResolveOptions


logger = logging.getLogger(__name__)


@goal_rule
async def resolve(
    targets: Targets,
    distdir: DistDir,
    workspace: Workspace,
    options: ResolveOptions,
    console: Console,
) -> ResolveGoal:

    if len(targets) != 1:
        raise ValueError(
            f"The `{options.name}` goal can currently only work with 1 target but given "
            f"{len(targets)} targets."
        )
    target = targets[0]
    if not isinstance(target, PythonLibrary):
        raise ValueError(
            f"The `{options.name}` goal currently only works with "
            f"`{PythonLibrary.alias}` targets but given a `{target.alias}` target."
        )

    resolved_result = await Get[ResolveResult](PythonLibrary, target)
    workspace.materialize_directory(
        DirectoryToMaterialize(
            digest=resolved_result.cache.snapshot.digest,
            path_prefix=str(distdir.relpath / options.name / target.address.path_safe_spec),
        )
    )

    with options.output_sink(console) as fp:
        resolved_result.dependencies.dump(fp)

    return ResolveGoal(exit_code=0)


def rules():
    return [create_resolver, resolve, resolve_target, resolve_requirements]
