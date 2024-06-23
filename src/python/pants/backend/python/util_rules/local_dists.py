# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
import shlex
from dataclasses import dataclass
from typing import Iterable

from pants.backend.python.subsystems.setuptools import PythonDistributionFieldSet
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.pex import Pex, PexRequest
from pants.backend.python.util_rules.pex import rules as pex_rules
from pants.backend.python.util_rules.pex_requirements import PexRequirements
from pants.backend.python.util_rules.python_sources import PythonSourceFiles
from pants.build_graph.address import Address
from pants.core.goals.package import BuiltPackage, PackageFieldSet
from pants.core.util_rules import system_binaries
from pants.core.util_rules.source_files import SourceFiles
from pants.core.util_rules.system_binaries import BashBinary, UnzipBinary
from pants.engine.addresses import Addresses
from pants.engine.fs import Digest, DigestSubset, MergeDigests, PathGlobs, Snapshot
from pants.engine.process import Process, ProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import (
    TransitiveTargets,
    TransitiveTargetsRequest,
    WrappedTarget,
    WrappedTargetRequest,
)
from pants.util.dirutil import fast_relpath_optional
from pants.util.docutil import doc_url
from pants.util.strutil import softwrap

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LocalDistWheels:
    """Contains the wheels isolated from a single local Python distribution."""

    wheel_paths: tuple[str, ...]
    wheels_digest: Digest
    provided_files: frozenset[str]


@rule
async def isolate_local_dist_wheels(
    dist_field_set: PythonDistributionFieldSet,
    bash: BashBinary,
    unzip_binary: UnzipBinary,
) -> LocalDistWheels:
    dist = await Get(BuiltPackage, PackageFieldSet, dist_field_set)
    wheels_snapshot = await Get(Snapshot, DigestSubset(dist.digest, PathGlobs(["**/*.whl"])))

    # A given local dist might build a wheel and an sdist (and maybe other artifacts -
    # we don't know what setup command was run...)
    # As long as there is a wheel, we can ignore the other artifacts.
    artifacts = {(a.relpath or "") for a in dist.artifacts}
    wheels = [wheel for wheel in wheels_snapshot.files if wheel in artifacts]

    if not wheels:
        tgt = await Get(
            WrappedTarget,
            WrappedTargetRequest(dist_field_set.address, description_of_origin="<infallible>"),
        )
        logger.warning(
            softwrap(
                f"""
                Encountered a dependency on the {tgt.target.alias} target at {dist_field_set.address},
                but this target does not produce a Python wheel artifact. Therefore this target's
                code will be used directly from sources, without a distribution being built,
                and any native extensions in it will not be built.

                See {doc_url('docs/python/overview/building-distributions')} for details on how to set up a
                {tgt.target.alias} target to produce a wheel.
                """
            )
        )

    wheels_listing_result = await Get(
        ProcessResult,
        Process(
            argv=[
                bash.path,
                "-c",
                f"""
                set -ex
                for f in {' '.join(shlex.quote(f) for f in wheels)}; do
                  {unzip_binary.path} -Z1 "$f"
                done
                """,
            ],
            input_digest=wheels_snapshot.digest,
            description=f"List contents of artifacts produced by {dist_field_set.address}",
        ),
    )
    provided_files = set(wheels_listing_result.stdout.decode().splitlines())

    return LocalDistWheels(
        tuple(sorted(wheels)), wheels_snapshot.digest, frozenset(sorted(provided_files))
    )


@dataclass(frozen=True)
class LocalDistsPexRequest:
    """Request to build the local dists from the dependency closure of a set of addresses."""

    addresses: Addresses
    interpreter_constraints: InterpreterConstraints
    # The result will return these with the sources provided by the dists subtracted out.
    # This will help the caller prevent sources from appearing twice on sys.path.
    sources: PythonSourceFiles

    def __init__(
        self,
        addresses: Iterable[Address],
        *,
        interpreter_constraints: InterpreterConstraints,
        sources: PythonSourceFiles = PythonSourceFiles.empty(),
    ) -> None:
        object.__setattr__(self, "addresses", Addresses(addresses))
        object.__setattr__(self, "interpreter_constraints", interpreter_constraints)
        object.__setattr__(self, "sources", sources)


@dataclass(frozen=True)
class LocalDistsPex:
    """A PEX file containing locally-built dists.

    Can be consumed from another PEX, e.g., by adding to PEX_PATH.

    The PEX will only contain locally built dists and not their dependencies. For Pants generated
    `setup.py` / `pyproject.toml`, the dependencies will be included in the standard resolve process
    that the locally-built dists PEX is adjoined to via PEX_PATH. For hand-made `setup.py` /
    `pyproject.toml` with 3rdparty dependencies not hand-mirrored into BUILD file dependencies, this
    will lead to issues. See https://github.com/pantsbuild/pants/issues/13587#issuecomment-974863636
    for one way to fix this corner which is intentionally punted on for now.

    Lists the files provided by the dists on sys.path, so they can be subtracted from
    sources digests, to prevent the same file ending up on sys.path twice.
    """

    pex: Pex
    # The sources from the request, but with any files provided by the local dists subtracted out.
    remaining_sources: PythonSourceFiles


@rule(desc="Building local distributions")
async def build_local_dists(
    request: LocalDistsPexRequest,
) -> LocalDistsPex:
    transitive_targets = await Get(TransitiveTargets, TransitiveTargetsRequest(request.addresses))
    applicable_targets = [
        tgt for tgt in transitive_targets.closure if PythonDistributionFieldSet.is_applicable(tgt)
    ]

    local_dists_wheels = await MultiGet(
        Get(LocalDistWheels, PythonDistributionFieldSet, PythonDistributionFieldSet.create(target))
        for target in applicable_targets
    )

    # The primary use-case of the "local dists" feature is to support consuming native extensions
    # as wheels without having to publish them first.
    # It doesn't seem very useful to consume locally-built sdists, and it makes it hard to
    # reason about possible sys.path collisions between the in-repo sources and whatever the
    # sdist will place on the sys.path when it's installed.
    # So for now we simply ignore sdists, with a warning if necessary.
    provided_files: set[str] = set()
    wheels: list[str] = []
    wheels_digests = []
    for local_dist_wheels in local_dists_wheels:
        wheels.extend(local_dist_wheels.wheel_paths)
        wheels_digests.append(local_dist_wheels.wheels_digest)
        provided_files.update(local_dist_wheels.provided_files)

    wheels_digest = await Get(Digest, MergeDigests(wheels_digests))

    dists_pex = await Get(
        Pex,
        PexRequest(
            output_filename="local_dists.pex",
            requirements=PexRequirements(wheels),
            interpreter_constraints=request.interpreter_constraints,
            additional_inputs=wheels_digest,
            # a "local dists" PEX is always just for consumption by some downstream Pants process,
            # i.e. internal
            internal_only=True,
            additional_args=["--intransitive"],
        ),
    )

    if not wheels:
        # The source calculations below are not (always) cheap, so we skip them if no wheels were
        # produced. See https://github.com/pantsbuild/pants/issues/14561 for one possible approach
        # to sharing the cost of these calculations.
        return LocalDistsPex(dists_pex, request.sources)

    # We check source roots in reverse lexicographic order,
    # so we'll find the innermost root that matches.
    source_roots = sorted(request.sources.source_roots, reverse=True)
    remaining_sources = set(request.sources.source_files.files)
    unrooted_files_set = set(request.sources.source_files.unrooted_files)
    for source in request.sources.source_files.files:
        if source not in unrooted_files_set:
            for source_root in source_roots:
                source_relpath = fast_relpath_optional(source, source_root)
                if source_relpath is not None and source_relpath in provided_files:
                    remaining_sources.remove(source)
    remaining_sources_snapshot = await Get(
        Snapshot,
        DigestSubset(
            request.sources.source_files.snapshot.digest, PathGlobs(sorted(remaining_sources))
        ),
    )
    subtracted_sources = PythonSourceFiles(
        SourceFiles(remaining_sources_snapshot, request.sources.source_files.unrooted_files),
        request.sources.source_roots,
    )

    return LocalDistsPex(dists_pex, subtracted_sources)


def rules():
    return (
        *collect_rules(),
        *pex_rules(),
        *system_binaries.rules(),
    )
