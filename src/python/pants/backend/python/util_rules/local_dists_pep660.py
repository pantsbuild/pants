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
from pants.backend.python.util_rules.pex_requirements import PexRequirements
from pants.backend.python.util_rules.python_sources import PythonSourceFiles
from pants.base.build_root import BuildRoot
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


# PEP 660 defines `prepare_metadata_for_build_editable`. If PEP 660 is not
# supported, we fall back to PEP 517's `prepare_metadata_for_build_wheel`.
# PEP 517, however, says that method is optional. So finally we fall back
# to using `build_wheel` and then extract the dist-info directory and then
# delete the extra wheel file. Most people shouldn't hit that path (I hope).
# NOTE: PEP 660 does not address the `.data` directory, so we ignore it.
_BACKEND_WRAPPER_BOILERPLATE = """
# DO NOT EDIT THIS FILE -- AUTOGENERATED BY PANTS

import os
import shutil
import sys
import zipfile
import {build_backend_module}

backend = {build_backend_object}

dist_dir = "{dist_dir}"
build_dir = "build"
pth_file_path = "{pth_file_path}"
wheel_config_settings = {wheel_config_settings_str}

# Python 2.7 doesn't have the exist_ok arg on os.makedirs().
for d in (dist_dir, build_dir):
    try:
        os.makedirs(d)
    except OSError as e:
        if e.errno != errno.EEXIST:
            raise

prepare_metadata = getattr(
    backend,
    "prepare_metadata_for_build_editable",  # PEP 660
    getattr(backend, "prepare_metadata_for_build_wheel", None)  # PEP 517
)
if prepare_metadata is not None:
    metadata_path = prepare_metadata(build_dir, wheel_config_settings)
else:
    # Optional PEP 517 method not defined. Use build_wheel instead.
    wheel_path = backend.build_wheel(build_dir, wheel_config_settings)
    full_wheel_path = os.path.join(build_dir, wheel_path)

    with zipfile.ZipFile(full_wheel_path, "r") as whl:
        dist_info_files = [n for n in whl.namelist() if ".dist-info/" in n]
        whl.extractall(build_dir, dist_info_files)
        metadata_path = os.path.dirname(dist_info_files[0])
    os.unlink(full_wheel_path)

for file in os.listdir(os.path.join(build_dir, metadata_path)):
    # PEP 660 excludes RECORD and RECORD.* (signatures)
    if file == "RECORD" or file.startswith("RECORD."):
        os.unlink(os.path.join(build_dir, metadata_path, file))

pkg, version = metadata_path.replace(".dist_info", "").split("-")
pth_file_dest = pkg + "__pants__.pth"

build_tag = "0.editable"  # copy of what setuptools uses
lang_tag = "py3"
abi_tag = "none"
platform_tag = "any"
wheel_path = "{}-{}-{}-{}-{}-{}.whl".format(
    pkg, version, build_tag, lang_tag, abi_tag, platform_tag
)
with zipfile.ZipFile(os.path.join(dist_dir, wheel_name), "w") as whl:
    whl.write(pth_file_path, pth_file_dest)
    # based on wheel.wheelfile.WheelFile.write_files (MIT license)
    for root, dirnames, filenames in os.walk(metadata_path):
        dirnames.sort()
        for name in sorted(filenames):
            path = os.path.normpath(os.path.join(root, name))
            if os.path.isfile(path):
                arcname = os.path.join(metadata_path, path)
                self.write(path, arcname)

print("editable_path: {{editable_path}}".format(editable_path=wheel_path))
"""


def interpolate_backend_wrapper(
    dist_dir: str,
    pth_file_path: str,
    request: DistBuildRequest,
) -> bytes:
    # See https://www.python.org/dev/peps/pep-0517/#source-trees.
    module_path, _, object_path = request.build_system.build_backend.partition(":")
    backend_object = f"{module_path}.{object_path}" if object_path else module_path

    def config_settings_repr(cs: FrozenDict[str, tuple[str, ...]] | None) -> str:
        # setuptools.build_meta expects list values and chokes on tuples.
        # We assume/hope that other backends accept lists as well.
        return distutils_repr(None if cs is None else {k: list(v) for k, v in cs.items()})

    return _BACKEND_WRAPPER_BOILERPLATE.format(
        build_backend_module=module_path,
        build_backend_object=backend_object,
        dist_dir=dist_dir,
        pth_file_path=pth_file_path,
        wheel_config_settings_str=config_settings_repr(request.wheel_config_settings),
    ).encode()


@rule
async def run_pep660_build(
    request: DistBuildRequest, python_setup: PythonSetup, build_root: BuildRoot
) -> PEP660BuildResult:
    # Create the .pth files to add the relevant source root to PYTHONPATH
    # We cannot use the build backend to do this because we do not want to tell
    # it where the workspace is and risk it adding anything there.
    # NOTE: We use .pth files to support ICs less than python3.7.
    #       A future enhancement might be to provide more precise editable
    #       wheels based on https://pypi.org/project/editables/, but that only
    #       supports python3.7+ (what pip supports as of April 2023).
    #       Or maybe do something like setuptools strict editable wheel.

    pth_file_contents = ""
    for source_root in request.build_time_source_roots:
        # can we use just the first one to only have the dist's source root?
        abs_path = (
            build_root.path if source_root == "." else str(build_root.pathlib_path / source_root)
        )
        pth_file_contents += f"{abs_path}\n"
    pth_file_path = os.path.join(request.working_directory, "__pants__.pth")
    pth_file_digest = await Get(
        Digest,
        CreateDigest([FileContent(pth_file_path, pth_file_contents.encode())]),
    )

    # Note that this pex has no entrypoint. We use it to run our generated wrapper, which
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

    backend_wrapper_name = "backend_wrapper.py"
    backend_wrapper_path = os.path.join(request.working_directory, backend_wrapper_name)
    backend_wrapper_digest = await Get(
        Digest,
        CreateDigest(
            [
                FileContent(
                    backend_wrapper_path,
                    interpolate_backend_wrapper(dist_output_dir, pth_file_path, request),
                ),
            ]
        ),
    )

    merged_digest = await Get(
        Digest, MergeDigests((request.input, pth_file_digest, backend_wrapper_digest))
    )

    extra_env = {
        **(request.extra_build_time_env or {}),
        "PEX_EXTRA_SYS_PATH": os.pathsep.join(request.build_time_source_roots),
    }
    if python_setup.macos_big_sur_compatibility and is_macos_big_sur():
        extra_env["MACOSX_DEPLOYMENT_TARGET"] = "10.16"

    result = await Get(
        ProcessResult,
        VenvPexProcess(
            build_backend_pex,
            argv=(backend_wrapper_name,),
            input_digest=merged_digest,
            extra_env=extra_env,
            working_directory=request.working_directory,
            output_directories=(dist_dir,),  # Relative to the working_directory.
            description=(
                f"Run {request.build_system.build_backend} to gather .dist-info for {request.target_address_spec}"
                if request.target_address_spec
                else f"Run {request.build_system.build_backend} to gather .dist-info"
            ),
            level=LogLevel.DEBUG,
        ),
    )
    output_lines = result.stdout.decode().splitlines()
    line_prefix = "editable_path: "
    editable_path = ""
    for line in output_lines:
        if line.startswith(line_prefix):
            editable_path = os.path.join(request.output_path, line[len(line_prefix) :].strip())
            break

    # Note that output_digest paths are relative to the working_directory.
    output_digest = await Get(Digest, RemovePrefix(result.output_digest, dist_dir))
    output_snapshot = await Get(Snapshot, Digest, output_digest)
    if editable_path not in output_snapshot.files:
        raise BuildBackendError(
            softwrap(
                f"""
                Failed to build PEP 660 editable wheel {editable_path}
                (extracted dist-info from PEP 517 build backend
                {request.build_system.build_backend}).
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
