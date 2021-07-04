# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass
from itertools import chain
from typing import Tuple

from pants.backend.java.compile.javac_binary import JavacBinary
from pants.backend.java.target_types import JavaSources
from pants.build_graph.address import Address
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.addresses import Addresses
from pants.engine.collection import Collection
from pants.engine.fs import EMPTY_DIGEST, AddPrefix, Digest, MergeDigests, RemovePrefix
from pants.engine.process import BashBinary, Process, ProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import (
    CoarsenedTargets,
    Dependencies,
    DependenciesRequest,
    Sources,
    Targets,
)
from pants.jvm.resolve.coursier_fetch import (
    CoursierLockfileForTargetRequest,
    CoursierResolvedLockfile,
    MaterializedClasspath,
    MaterializedClasspathRequest,
)
from pants.jvm.resolve.coursier_setup import Coursier
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CompileJavaSourceRequest:
    targets: CoarsenedTargets


@dataclass(frozen=True)
class CompiledClassfiles:
    digest: Digest


class CoarsenedComponents(Collection[CoarsenedTargets]):
    pass


def canonical_addresses_for_coarsened_targets(
    coarsened_targets: CoarsenedTargets,
) -> Tuple[Address, ...]:
    """Return the unique, sorted addresses for a CoarsenedTargets collection.

    This is useful as a canonical ID (e.g. dictionary key) for CoarsenedTargets.

    TODO: Maybe this should be a memoized property of CoarsenedTargets.
    """
    return tuple(sorted(frozenset(t.address for t in coarsened_targets)))


@rule
async def coarsened_components(addresses: Addresses) -> CoarsenedComponents:
    """Returns a deduplicated collection of CoarsenedTargets computed from the input 'addresses'.

    TODO: It might be worthwhile to add some additional validation here that the resulting components
      are mutually disjoint.  This should be guaranteed by the coarsening logic, but if for some
      reason that assumption doesn't hold the resulting behavior could be very difficult to debug.
    TODO: There is a tradeoff between parallelism and total cycles here, and it's unclear which is
      better for performance.  Another implementation could gather one coarsened component at a time
      and only request CoarsenedTargets for remaining addresses that weren't covered by the components
      already computed.  In practice, this code is unlikely to contribute substantially to
      performance either way, and any optimization should probably be done with global memoization
      at the level of the native coarsening libraries.
    TODO: This rule is probably useful outside of javac, in which case it should be hoisted into
      a generic rule in graph.py.
    """

    all_coarsened_components = await MultiGet(
        Get(CoarsenedTargets, Address, address) for address in addresses
    )
    # Remove any potential duplicate components (e.g. if some of the input addresses ended up in the same component)
    # by utilizing the fact that dict()'s constructor automatically deduplicates inputs based on key value.
    component_id_to_component = FrozenDict(
        (canonical_addresses_for_coarsened_targets(coarsened_targets), coarsened_targets)
        for coarsened_targets in all_coarsened_components
    )
    return CoarsenedComponents(
        tuple(
            component
            for _, component in sorted(component_id_to_component.items(), key=lambda x: x[0])
        )
    )


@rule(level=LogLevel.DEBUG)
async def compile_java_source(
    bash: BashBinary,
    coursier: Coursier,
    javac_binary: JavacBinary,
    request: CompileJavaSourceRequest,
) -> CompiledClassfiles:
    targets_and_source_files = zip(
        request.targets,
        await MultiGet(
            Get(
                SourceFiles,
                SourceFilesRequest(
                    (target.get(Sources),),
                    for_sources_types=(JavaSources,),
                    enable_codegen=True,
                ),
            )
            for target in request.targets
            if target.has_field(JavaSources)
        ),
    )

    filtered_targets_and_source_files = [
        (target, sources)
        for target, sources in targets_and_source_files
        if sources.snapshot.digest != EMPTY_DIGEST
    ]

    if not filtered_targets_and_source_files:
        return CompiledClassfiles(digest=EMPTY_DIGEST)

    direct_deps = Addresses(
        sorted(
            frozenset(
                chain.from_iterable(
                    await MultiGet(
                        Get(Addresses, DependenciesRequest(target[Dependencies]))
                        for target, _ in filtered_targets_and_source_files
                    )
                )
            )
        )
    )

    canonical_request_component = frozenset(
        canonical_addresses_for_coarsened_targets(request.targets)
    )

    # It's possible that a target in our input set of coarsened targets has a direct
    # dependency on another target within the input component (indeed this is guaranteed
    # to happen if the input component has more than 1 target); therefore we filter out
    # direct dep components that have any intersection with the input component to avoid
    # a rule cycle.
    # TODO: Consider adding some further sanity checks to ensure that if there is any intersection,
    #   then it is actually a full equality of components rather than a partial overlap.
    #   In theory this should be guaranteed by the coarsening logic.
    all_coarsened_components = await Get(CoarsenedComponents, Addresses, direct_deps)
    coarsened_dep_components = CoarsenedComponents(
        coarsened_targets
        for coarsened_targets in all_coarsened_components
        if canonical_request_component.isdisjoint(
            frozenset(canonical_addresses_for_coarsened_targets(coarsened_targets))
        )
    )
    lockfile = await Get(
        CoursierResolvedLockfile, CoursierLockfileForTargetRequest(Targets(request.targets))
    )
    direct_dependency_classfiles = await MultiGet(
        Get(CompiledClassfiles, CompileJavaSourceRequest(targets=coarsened_targets))
        for coarsened_targets in coarsened_dep_components
    )
    materialized_classpath, merged_direct_dependency_classfiles_digest = await MultiGet(
        Get(
            MaterializedClasspath,
            MaterializedClasspathRequest(
                prefix="__thirdpartycp",
                lockfiles=(lockfile,),
            ),
        ),
        Get(Digest, MergeDigests(classfiles.digest for classfiles in direct_dependency_classfiles)),
    )

    usercp_relpath = "__usercp"
    prefixed_direct_dependency_classfiles_digest = await Get(
        Digest, AddPrefix(merged_direct_dependency_classfiles_digest, usercp_relpath)
    )

    classpath_arg = usercp_relpath
    third_party_classpath_arg = materialized_classpath.classpath_arg()
    if third_party_classpath_arg:
        classpath_arg = ":".join([classpath_arg, third_party_classpath_arg])

    merged_digest = await Get(
        Digest,
        MergeDigests(
            (
                prefixed_direct_dependency_classfiles_digest,
                materialized_classpath.digest,
                javac_binary.digest,
                *(sources.snapshot.digest for _, sources in filtered_targets_and_source_files),
            )
        ),
    )

    process_result = await Get(
        ProcessResult,
        Process(
            argv=[
                bash.path,
                javac_binary.javac_wrapper_script,
                "-cp",
                classpath_arg,
                "-d",
                "classfiles",
                *sorted(
                    chain.from_iterable(
                        sources.snapshot.files for _, sources in filtered_targets_and_source_files
                    )
                ),
            ],
            input_digest=merged_digest,
            output_directories=("classfiles",),
            description=f"Compile {request.targets} with javac",
            level=LogLevel.DEBUG,
        ),
    )
    stripped_classfiles_digest = await Get(
        Digest, RemovePrefix(process_result.output_digest, "classfiles")
    )
    return CompiledClassfiles(digest=stripped_classfiles_digest)


def rules():
    return [
        *collect_rules(),
    ]
