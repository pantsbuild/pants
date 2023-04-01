# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
import os
import shlex
from dataclasses import dataclass
from typing import Iterable

# TODO: move this to a util_rules file
from pants.backend.python.goals.setup_py import create_dist_build_request
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.subsystems.setuptools import PythonDistributionFieldSet
from pants.backend.python.util_rules.dists import (
    BuildBackendError,
    DistBuildRequest,
    distutils_repr,
)
from pants.backend.python.util_rules.dists import rules as dists_rules
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.pex import Pex, PexRequest, VenvPex, VenvPexProcess
from pants.backend.python.util_rules.pex_requirements import EntireLockfile, PexRequirements
from pants.backend.python.util_rules.python_sources import PythonSourceFiles
from pants.build_graph.address import Address
from pants.core.util_rules import system_binaries
from pants.core.util_rules.source_files import SourceFiles
from pants.core.util_rules.system_binaries import BashBinary, UnzipBinary
from pants.engine.addresses import Addresses
from pants.engine.fs import (
    CreateDigest,
    Digest,
    DigestSubset,
    FileContent,
    MergeDigests,
    PathGlobs,
    RemovePrefix,
    Snapshot,
)
from pants.engine.process import Process, ProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import (
    TransitiveTargets,
    TransitiveTargetsRequest,
    WrappedTarget,
    WrappedTargetRequest,
)
from pants.engine.unions import UnionMembership
from pants.util.dirutil import fast_relpath_optional
from pants.util.docutil import doc_url
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.osutil import is_macos_big_sur
from pants.util.strutil import softwrap

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LocalDistPEP660Wheels:  # Based on LocalDistWheels
    """Contains the PEP 660 "editable" wheels isolated from a single local Python distribution."""

    pep660_wheel_paths: tuple[str, ...]
    pep660_wheels_digest: Digest
    provided_files: frozenset[str]


@rule
async def isolate_local_dist_pep660_wheels(
    dist_field_set: PythonDistributionFieldSet,
    bash: BashBinary,
    unzip_binary: UnzipBinary,
    python_setup: PythonSetup,
    union_membership: UnionMembership,
) -> LocalDistPEP660Wheels:
    dist_build_request = await create_dist_build_request(
        field_set=dist_field_set,
        python_setup=python_setup,
        union_membership=union_membership,
        # editable wheel ignores build_wheel+build_sdist args
        validate_wheel_sdist=False,
    )
    pep660_result = await Get(PEP660BuildResult, DistBuildRequest, dist_build_request)

    # the output digest should only contain wheels, but filter to be safe.
    wheels_snapshot = await Get(
        Snapshot, DigestSubset(pep660_result.output, PathGlobs(["**/*.whl"]))
    )

    wheels = tuple(wheels_snapshot.files)

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

                See {doc_url('python-distributions')} for details on how to set up a
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
            description=f"List contents of editable artifacts produced by {dist_field_set.address}",
        ),
    )
    provided_files = set(wheels_listing_result.stdout.decode().splitlines())

    return LocalDistPEP660Wheels(wheels, wheels_snapshot.digest, frozenset(provided_files))


@dataclass(frozen=True)
class LocalDistsPEP660PexRequest:
    """Request to build a PEX populated by PEP660 wheels of local dists.

    Like LocalDistsPexRequest, the local dists come from the dependency closure of a set of
    addresses. Unlike LocalDistsPexRequest, the editable wheel files must not be exported or made
    available to the end-user (according to PEP 660). Instead, the PEP660Pex serves as an
    intermediate, internal-only, PEX that can be used to install these wheels in a virtualenv. It
    follows then, that this PEX should probably not be exported for use by end-users.
    """

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
class LocalDistsPEP660Pex:
    """A PEX file populated by PEP660 wheels of local dists.

    Can be consumed from another PEX, e.g., by adding to PEX_PATH.

    The PEX will contain installs of PEP660 wheels generate4d from local dists. Installing PEP660
    wheels creates an "editable" install such that the sys.path gets adjusted to include source
    directories that are NOT part of the PEX. As such, this PEX is decidedly not hermetic or
    portable and should only be used to facilitate building virtualenvs for development.

    PEP660 wheels have .dist-info metadata and the .pth files (or similar) that adjust sys.path.

    The PEX will only contain metadata for local dists and not any dependencies. For Pants generated
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
    # In general, this will have a list of all of the dists' sources.
    remaining_sources: PythonSourceFiles


@rule(desc="Building editable local distributions (PEP 660)")
async def build_editable_local_dists(
    request: LocalDistsPEP660PexRequest,
) -> LocalDistsPEP660Pex:
    transitive_targets = await Get(TransitiveTargets, TransitiveTargetsRequest(request.addresses))
    applicable_targets = [
        tgt for tgt in transitive_targets.closure if PythonDistributionFieldSet.is_applicable(tgt)
    ]

    local_dists_wheels = await MultiGet(
        Get(
            LocalDistPEP660Wheels,
            PythonDistributionFieldSet,
            PythonDistributionFieldSet.create(target),
        )
        for target in applicable_targets
    )

    provided_files: set[str] = set()
    wheels: list[str] = []
    wheels_digests = []
    for local_dist_wheels in local_dists_wheels:
        wheels.extend(local_dist_wheels.pep660_wheel_paths)
        wheels_digests.append(local_dist_wheels.pep660_wheels_digest)
        provided_files.update(local_dist_wheels.provided_files)

    wheels_digest = await Get(Digest, MergeDigests(wheels_digests))

    editable_dists_pex = await Get(
        Pex,
        PexRequest(
            output_filename="editable_local_dists.pex",
            requirements=PexRequirements(wheels),
            interpreter_constraints=request.interpreter_constraints,
            additional_inputs=wheels_digest,
            internal_only=True,
            additional_args=["--intransitive"],
        ),
    )

    if not wheels:
        # The source calculations below are not (always) cheap, so we skip them if no wheels were
        # produced. See https://github.com/pantsbuild/pants/issues/14561 for one possible approach
        # to sharing the cost of these calculations.
        return LocalDistsPEP660Pex(editable_dists_pex, request.sources)

    # TODO: maybe DRY the logic duplicated here and in build_local_dists
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

    return LocalDistsPEP660Pex(editable_dists_pex, subtracted_sources)


# We just use DistBuildRequest directly instead of adding a PEP660BuildRequest


@dataclass(frozen=True)
class PEP660BuildResult:  # Based on DistBuildResult
    output: Digest
    # Relpaths in the output digest.
    editable_wheel_path: str | None


# Sadly we have to call this shim twice, once to get any additional requirements
# and then, once those requirements are included in the build backend pex,
# to actually build the editable wheel.
_BACKEND_SHIM_BOILERPLATE = """
# DO NOT EDIT THIS FILE -- AUTOGENERATED BY PANTS

import os
import sys
import {build_backend_module}

backend = {build_backend_object}

dist_dir = "{dist_dir}"
get_editable_requires = {get_requires}
build_editable = {build_editable}
wheel_config_settings = {wheel_config_settings_str}

if get_requires:
    editable_requires = backend.get_requires_for_build_editable(wheel_config_settings)
    for pep508_req in editable_requires:
        print("editable_requires: {{pep508_req}}".format(pep508_req=pep508_req))

if not build_editable:
    sys.exit(0)

# Python 2.7 doesn't have the exist_ok arg on os.makedirs().
try:
    os.makedirs(dist_dir)
except OSError as e:
    if e.errno != errno.EEXIST:
        raise

editable_path = backend.build_editable(dist_dir, wheel_config_settings)
print("editable: {{editable_path}}".format(editable_path=editable_path))
"""


def interpolate_backend_shim(
    dist_dir: str,
    request: DistBuildRequest,
    get_editable_requires: bool = False,
    build_editable: bool = False,
) -> bytes:
    # See https://www.python.org/dev/peps/pep-0517/#source-trees.
    module_path, _, object_path = request.build_system.build_backend.partition(":")
    backend_object = f"{module_path}.{object_path}" if object_path else module_path

    def config_settings_repr(cs: FrozenDict[str, tuple[str, ...]] | None) -> str:
        # setuptools.build_meta expects list values and chokes on tuples.
        # We assume/hope that other backends accept lists as well.
        return distutils_repr(None if cs is None else {k: list(v) for k, v in cs.items()})

    return _BACKEND_SHIM_BOILERPLATE.format(
        build_backend_module=module_path,
        build_backend_object=backend_object,
        dist_dir=dist_dir,
        get_editable_requires=get_editable_requires,
        build_editable=build_editable,
        wheel_config_settings_str=config_settings_repr(request.wheel_config_settings),
    ).encode()


@rule
async def run_pep660_build(
    request: DistBuildRequest, python_setup: PythonSetup
) -> PEP660BuildResult:
    # Note that this pex has no entrypoint. We use it to run our generated shim, which
    # in turn imports from and invokes the build backend.
    build_backend_pex = await Get(
        VenvPex,
        PexRequest(
            output_filename="build_backend.pex",
            internal_only=True,
            requirements=request.build_system.requires,
            pex_path=request.extra_build_time_requirements,
            interpreter_constraints=request.interpreter_constraints,
        ),
    )

    # This is the setuptools dist directory, not Pants's, so we hardcode to dist/.
    dist_dir = "dist"
    dist_output_dir = os.path.join(dist_dir, request.output_path)
    backend_shim_name = "backend_shim.py"
    backend_shim_path = os.path.join(request.working_directory, backend_shim_name)
    get_requires_backend_shim_digest = await Get(
        Digest,
        CreateDigest(
            [
                FileContent(
                    backend_shim_path,
                    interpolate_backend_shim(dist_output_dir, request, get_editable_requires=True),
                ),
            ]
        ),
    )
    build_editable_backend_shim_digest = await Get(
        Digest,
        CreateDigest(
            [
                FileContent(
                    backend_shim_path,
                    interpolate_backend_shim(dist_output_dir, request, build_editable=True),
                ),
            ]
        ),
    )

    get_requires_merged_digest = await Get(
        Digest, MergeDigests((request.input, get_requires_backend_shim_digest))
    )
    build_editable_merged_digest = await Get(
        Digest, MergeDigests((request.input, build_editable_backend_shim_digest))
    )

    extra_env = {
        **(request.extra_build_time_env or {}),
        "PEX_EXTRA_SYS_PATH": os.pathsep.join(request.build_time_source_roots),
    }
    if python_setup.macos_big_sur_compatibility and is_macos_big_sur():
        extra_env["MACOSX_DEPLOYMENT_TARGET"] = "10.16"

    requires_result = await Get(
        ProcessResult,
        VenvPexProcess(
            build_backend_pex,
            argv=(backend_shim_name,),
            input_digest=get_requires_merged_digest,
            extra_env=extra_env,
            working_directory=request.working_directory,
            output_directories=(dist_dir,),  # Relative to the working_directory.
            description=(
                f"Run {request.build_system.build_backend} (get_requires_for_build_editable) for {request.target_address_spec}"
                if request.target_address_spec
                else f"Run {request.build_system.build_backend} (get_requires_for_build_editable)"
            ),
            level=LogLevel.DEBUG,
        ),
    )
    requires_output_lines = requires_result.stdout.decode().splitlines()
    editable_requires_prefix = "editable_requires: "
    editable_requires_prefix_len = len(editable_requires_prefix)
    editable_requires = []
    for line in requires_output_lines:
        if line.startswith(editable_requires_prefix):
            editable_requires.append(line[editable_requires_prefix_len:].strip())

    # if there are any editable_requires, then we have to build another PEX with those requirements.
    if editable_requires:
        if isinstance(request.build_system.requires, EntireLockfile):
            req_strings = list(request.build_system.requires.complete_req_strings or ())
        else:
            req_strings = list(request.build_system.requires.req_strings)
        # recreate the build_backend_pex but include the additional requirements
        build_backend_pex = await Get(
            VenvPex,
            PexRequest(
                output_filename="build_backend.pex",
                internal_only=True,
                requirements=PexRequirements(list(req_strings) + editable_requires),
                pex_path=request.extra_build_time_requirements,
                interpreter_constraints=request.interpreter_constraints,
            ),
        )

    result = await Get(
        ProcessResult,
        VenvPexProcess(
            build_backend_pex,
            argv=(backend_shim_name,),
            input_digest=build_editable_merged_digest,
            extra_env=extra_env,
            working_directory=request.working_directory,
            output_directories=(dist_dir,),  # Relative to the working_directory.
            description=(
                f"Run {request.build_system.build_backend} (build_editable) for {request.target_address_spec}"
                if request.target_address_spec
                else f"Run {request.build_system.build_backend} (build_editable)"
            ),
            level=LogLevel.DEBUG,
        ),
    )
    output_lines = result.stdout.decode().splitlines()
    dist_type = "editable"
    editable_path = ""
    for line in output_lines:
        if line.startswith(f"{dist_type}: "):
            editable_path = os.path.join(request.output_path, line[len(dist_type) + 2 :].strip())
            break

    # Note that output_digest paths are relative to the working_directory.
    output_digest = await Get(Digest, RemovePrefix(result.output_digest, dist_dir))
    output_snapshot = await Get(Snapshot, Digest, output_digest)
    if editable_path not in output_snapshot.files:
        raise BuildBackendError(
            softwrap(
                f"""
                PEP 660 build backend {request.build_system.build_backend}
                did not create expected editable wheel file {editable_path}
                """
            )
        )
    return PEP660BuildResult(output_digest, editable_wheel_path=editable_path)


def rules():
    return (
        *collect_rules(),
        *dists_rules(),
        *system_binaries.rules(),
    )
