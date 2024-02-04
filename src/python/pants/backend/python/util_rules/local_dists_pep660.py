# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import json
import logging
import os
import shlex
from collections import defaultdict
from dataclasses import dataclass
from pathlib import PurePath

from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.subsystems.setuptools import PythonDistributionFieldSet
from pants.backend.python.target_types import PythonProvidesField, PythonResolveField
from pants.backend.python.util_rules import package_dists
from pants.backend.python.util_rules.dists import BuildBackendError, DistBuildRequest
from pants.backend.python.util_rules.dists import rules as dists_rules
from pants.backend.python.util_rules.package_dists import (
    DependencyOwner,
    ExportedTarget,
    OwnedDependencies,
    create_dist_build_request,
)
from pants.backend.python.util_rules.pex import PexRequest, VenvPex, VenvPexProcess
from pants.base.build_root import BuildRoot
from pants.core.util_rules import system_binaries
from pants.core.util_rules.system_binaries import BashBinary, UnzipBinary
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
from pants.engine.target import AllTargets, Target, Targets, WrappedTarget, WrappedTargetRequest
from pants.engine.unions import UnionMembership
from pants.source.source_root import SourceRootRequest, SourceRoot
from pants.util.docutil import doc_url
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.osutil import is_macos_big_sur
from pants.util.resources import read_resource
from pants.util.strutil import softwrap

logger = logging.getLogger(__name__)


_scripts_package = "pants.backend.python.util_rules.scripts"


@dataclass(frozen=True)
class PEP660BuildResult:
    output: Digest
    # Relpaths in the output digest.
    editable_wheel_path: str | None


def dump_backend_wrapper_json(
    dist_dir: str,
    pth_file_path: str,
    direct_url: str,
    request: DistBuildRequest,
) -> bytes:
    """Build the settings json for our PEP 517 / PEP 660 wrapper script."""

    def clean_config_settings(
        cs: FrozenDict[str, tuple[str, ...]] | None
    ) -> dict[str, list[str]] | None:
        # setuptools.build_meta expects list values and chokes on tuples.
        # We assume/hope that other backends accept lists as well.
        return None if cs is None else {k: list(v) for k, v in cs.items()}

    # tag the editable wheel as widely compatible
    lang_tag, abi_tag, platform_tag = "py3", "none", "any"
    if request.interpreter_constraints.includes_python2():
        # Assume everything has py3 support. If not, we'll need a new includes_python3 method.
        lang_tag = "py2.py3"

    settings = {
        "build_backend": request.build_system.build_backend,
        "dist_dir": dist_dir,
        "pth_file_path": pth_file_path,
        "wheel_config_settings": clean_config_settings(request.wheel_config_settings),
        "tags": "-".join([lang_tag, abi_tag, platform_tag]),
        "direct_url": direct_url,
    }
    return json.dumps(settings).encode()


@rule
async def run_pep660_build(
    request: DistBuildRequest, python_setup: PythonSetup, build_root: BuildRoot
) -> PEP660BuildResult:
    """Run our PEP 517 / PEP 660 wrapper script to generate an editable wheel.

    The PEP 517 / PEP 660 wraper script is responsible for building the editable wheel.
    The backend wrapper script, along with the commands that install the editable wheel,
    need to conform to the following specs so that Pants is a PEP 660 compliant frontend,
    a PEP 660 compliant backend, and that it builds a compliant wheel and install.

    NOTE: PEP 660 does not address the `.data` directory, so the wrapper ignores it.

    Relevant Specs:
      https://peps.python.org/pep-0517/
      https://peps.python.org/pep-0660/
      https://packaging.python.org/en/latest/specifications/platform-compatibility-tags/
      https://packaging.python.org/en/latest/specifications/recording-installed-packages/
      https://packaging.python.org/en/latest/specifications/direct-url-data-structure/
      https://packaging.python.org/en/latest/specifications/binary-distribution-format/
    """
    dist_abs_path = (
        build_root.path
        if request.dist_source_root == "."
        else str(build_root.pathlib_path / request.dist_source_root)
    )
    direct_url = "file://" + dist_abs_path.replace(os.path.sep, "/")

    # Create the .pth files to add the relevant source root to sys.path.
    # We cannot use the build backend to do this because we do not want to tell
    # it where the workspace is and risk it adding anything there.
    # NOTE: We use .pth files to support ICs less than python3.7.
    #       A future enhancement might be to provide more precise editable
    #       wheels based on https://pypi.org/project/editables/, but that only
    #       supports python3.7+ (what pip supports as of April 2023).
    #       Or maybe do something like setuptools strict editable wheel.
    pth_file_contents = ""
    for source_root in request.build_time_source_roots:  # NB: the roots are sorted
        # Can we use just the dist_abs_path instead of including all source roots?
        abs_path = (
            build_root.path if source_root == "." else str(build_root.pathlib_path / source_root)
        )
        pth_file_contents += f"{abs_path}\n"
    pth_file_name = "__pants__.pth"
    pth_file_path = os.path.join(request.working_directory, pth_file_name)

    # This is the setuptools dist directory, not Pants's, so we hardcode to dist/.
    dist_dir = "dist"
    dist_output_dir = os.path.join(dist_dir, request.output_path)

    backend_wrapper_json = "backend_wrapper.json"
    backend_wrapper_json_path = os.path.join(request.working_directory, backend_wrapper_json)
    backend_wrapper_name = "backend_wrapper.py"
    backend_wrapper_path = os.path.join(request.working_directory, backend_wrapper_name)
    backend_wrapper_content = read_resource(_scripts_package, "pep660_backend_wrapper.py")
    assert backend_wrapper_content is not None

    conf_digest, backend_wrapper_digest, build_backend_pex = await MultiGet(
        Get(
            Digest,
            CreateDigest(
                [
                    FileContent(pth_file_path, pth_file_contents.encode()),
                    FileContent(
                        backend_wrapper_json_path,
                        dump_backend_wrapper_json(
                            dist_output_dir, pth_file_name, direct_url, request
                        ),
                    ),
                ]
            ),
        ),
        # The backend_wrapper has its own digest for cache reuse.
        Get(
            Digest,
            CreateDigest([FileContent(backend_wrapper_path, backend_wrapper_content)]),
        ),
        # Note that this pex has no entrypoint. We use it to run our wrapper, which
        # in turn imports from and invokes the build backend.
        Get(
            VenvPex,
            PexRequest(
                output_filename="build_backend.pex",
                internal_only=True,
                requirements=request.build_system.requires,
                pex_path=request.extra_build_time_requirements,
                interpreter_constraints=request.interpreter_constraints,
            ),
        ),
    )

    merged_digest = await Get(
        Digest, MergeDigests((request.input, conf_digest, backend_wrapper_digest))
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
            argv=(backend_wrapper_name, backend_wrapper_json),
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


@dataclass(frozen=True)
class LocalDistPEP660Wheels:
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
class AllPythonDistributionTargets:
    targets: Targets


@rule(desc="Find all Python Distribution targets in project", level=LogLevel.DEBUG)
def find_all_python_distributions(
    all_targets: AllTargets,
) -> AllPythonDistributionTargets:
    return AllPythonDistributionTargets(
        # 'provides' is the field used in PythonDistributionFieldSet
        Targets(tgt for tgt in all_targets if tgt.has_field(PythonProvidesField))
    )


@dataclass(frozen=True)
class ResolveSortedPythonDistributionTargets:
    targets: FrozenDict[str | None, tuple[Target, ...]]


@rule(
    desc="Associate resolves with all Python Distribution targets in project", level=LogLevel.DEBUG
)
async def sort_all_python_distributions_by_resolve(
    all_dists: AllPythonDistributionTargets,
    python_setup: PythonSetup,
) -> ResolveSortedPythonDistributionTargets:
    dists = defaultdict(list)

    if not python_setup.enable_resolves:
        resolve = None
        return ResolveSortedPythonDistributionTargets(
            FrozenDict({resolve: tuple(all_dists.targets)})
        )

    dist_owned_deps = await MultiGet(
        Get(OwnedDependencies, DependencyOwner(ExportedTarget(tgt))) for tgt in all_dists.targets
    )

    for dist, owned_deps in zip(all_dists.targets, dist_owned_deps):
        resolve = None
        # assumption: all owned deps are in the same resolve
        for dep in owned_deps:
            if dep.target.has_field(PythonResolveField):
                resolve = dep.target[PythonResolveField].normalized_value(python_setup)
                break
        dists[resolve].append(dist)
    return ResolveSortedPythonDistributionTargets(
        FrozenDict({resolve: tuple(targets) for resolve, targets in dists.items()})
    )


@dataclass(frozen=True)
class EditableLocalDistsRequest:
    """Request to generate PEP660 wheels of local dists in the given resolve.

    The editable wheel files must not be exported or made available to the end-user (according to
    PEP 660). Instead, the PEP660 editable wheels serve as intermediate, internal-only,
    representation of what should be installed in the exported virtualenv to create the editable
    installs of local python_distributions.
    """

    resolve: str | None  # None if resolves is not enabled


@dataclass(frozen=True)
class EditableLocalDists:
    """A Digest populated by editable (PEP660) wheels of local dists.

    According to PEP660, these wheels should not be exported to users and must be discarded
    after install. Anything that uses this should ensure that these wheels get installed and
    then deleted.

    Installing PEP660 wheels creates an "editable" install such that the sys.path gets
    adjusted to include source directories from the build root (not from the sandbox).
    This is decidedly not hermetic or portable and should only be used locally.

    PEP660 wheels have .dist-info metadata and the .pth files (or similar) that adjust sys.path.
    """

    optional_digest: Digest | None


@rule(desc="Building editable local distributions (PEP 660)")
async def build_editable_local_dists(
    request: EditableLocalDistsRequest,
    all_dists: ResolveSortedPythonDistributionTargets,
    python_setup: PythonSetup,
) -> EditableLocalDists:
    resolve = request.resolve if python_setup.enable_resolves else None
    resolve_dists = all_dists.targets.get(resolve, ())

    if not resolve_dists:
        return EditableLocalDists(None)

    local_dists_wheels = await MultiGet(
        Get(
            LocalDistPEP660Wheels,
            PythonDistributionFieldSet,
            PythonDistributionFieldSet.create(target),
        )
        for target in resolve_dists
    )

    wheels: list[str] = []
    wheels_digests = []
    for local_dist_wheels in local_dists_wheels:
        wheels.extend(local_dist_wheels.pep660_wheel_paths)
        wheels_digests.append(local_dist_wheels.pep660_wheels_digest)

    wheels_digest = await Get(Digest, MergeDigests(wheels_digests))

    return EditableLocalDists(wheels_digest)


def rules():
    return (
        *collect_rules(),
        *dists_rules(),
        *package_dists.rules(),
        *system_binaries.rules(),
    )
