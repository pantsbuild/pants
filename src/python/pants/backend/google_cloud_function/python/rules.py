# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass

from pants.backend.google_cloud_function.python.target_types import (
    PythonGoogleCloudFunctionHandlerField,
    PythonGoogleCloudFunctionRuntime,
    PythonGoogleCloudFunctionType,
    ResolvedPythonGoogleHandler,
    ResolvePythonGoogleHandlerRequest,
)
from pants.backend.python.subsystems.lambdex import Lambdex
from pants.backend.python.target_types import PexCompletePlatformsField
from pants.backend.python.util_rules import pex_from_targets
from pants.backend.python.util_rules.pex import (
    CompletePlatforms,
    Pex,
    PexPlatforms,
    PexRequest,
    VenvPex,
    VenvPexProcess,
)
from pants.backend.python.util_rules.pex_from_targets import PexFromTargetsRequest
from pants.core.goals.package import (
    BuiltPackage,
    BuiltPackageArtifact,
    OutputPathField,
    PackageFieldSet,
)
from pants.core.target_types import FileSourceField
from pants.engine.platform import Platform
from pants.engine.process import ProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import (
    TransitiveTargets,
    TransitiveTargetsRequest,
    targets_with_sources_types,
)
from pants.engine.unions import UnionMembership, UnionRule
from pants.util.docutil import bin_name, doc_url
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PythonGoogleCloudFunctionFieldSet(PackageFieldSet):
    required_fields = (PythonGoogleCloudFunctionHandlerField,)

    handler: PythonGoogleCloudFunctionHandlerField
    runtime: PythonGoogleCloudFunctionRuntime
    complete_platforms: PexCompletePlatformsField
    type: PythonGoogleCloudFunctionType
    output_path: OutputPathField


@rule(desc="Create Python Google Cloud Function", level=LogLevel.DEBUG)
async def package_python_google_cloud_function(
    field_set: PythonGoogleCloudFunctionFieldSet,
    lambdex: Lambdex,
    platform: Platform,
    union_membership: UnionMembership,
) -> BuiltPackage:
    if platform.is_macos:
        logger.warning(
            "Google Cloud Functions built on macOS may fail to build. If your function uses any"
            " third-party dependencies without binary wheels (bdist) for Linux available, it will"
            " fail to build. If this happens, you will either need to update your dependencies to"
            " only use dependencies with pre-built wheels, or find a Linux environment to run"
            f" {bin_name()} package. (See https://realpython.com/python-wheels/ for more about"
            " wheels.)\n\n(If the build does not raise an exception, it's safe to use macOS.)"
        )

    output_filename = field_set.output_path.value_or_default(
        # Cloud Functions typically use the .zip suffix, so we use that instead of .pex.
        file_ending="zip",
    )

    # We hardcode the platform value to the appropriate one for each Google Cloud Function runtime.
    # (Running the "hello world" cloud function in the example code will report the platform, and can be
    # used to verify correctness of these platform strings.)
    pex_platforms = []
    interpreter_version = field_set.runtime.to_interpreter_version()
    if interpreter_version:
        py_major, py_minor = interpreter_version
        platform_str = f"linux_x86_64-cp-{py_major}{py_minor}-cp{py_major}{py_minor}"
        # set pymalloc ABI flag - this was removed in python 3.8 https://bugs.python.org/issue36707
        if py_major <= 3 and py_minor < 8:
            platform_str += "m"
        pex_platforms.append(platform_str)

    additional_pex_args = (
        # Ensure we can resolve manylinux wheels in addition to any AMI-specific wheels.
        "--manylinux=manylinux2014",
        # When we're executing Pex on Linux, allow a local interpreter to be resolved if
        # available and matching the AMI platform.
        "--resolve-local-platforms",
    )

    complete_platforms = await Get(
        CompletePlatforms, PexCompletePlatformsField, field_set.complete_platforms
    )

    pex_request = PexFromTargetsRequest(
        addresses=[field_set.address],
        internal_only=False,
        output_filename=output_filename,
        platforms=PexPlatforms(pex_platforms),
        complete_platforms=complete_platforms,
        additional_args=additional_pex_args,
        additional_lockfile_args=additional_pex_args,
    )

    lambdex_request = PexRequest(
        output_filename="lambdex.pex",
        internal_only=True,
        requirements=lambdex.pex_requirements(),
        interpreter_constraints=lambdex.interpreter_constraints,
        main=lambdex.main,
    )

    lambdex_pex, pex_result, handler, transitive_targets = await MultiGet(
        Get(VenvPex, PexRequest, lambdex_request),
        Get(Pex, PexFromTargetsRequest, pex_request),
        Get(ResolvedPythonGoogleHandler, ResolvePythonGoogleHandlerRequest(field_set.handler)),
        Get(TransitiveTargets, TransitiveTargetsRequest([field_set.address])),
    )

    # Warn if users depend on `files` targets, which won't be included in the PEX and is a common
    # gotcha.
    file_tgts = targets_with_sources_types(
        [FileSourceField], transitive_targets.dependencies, union_membership
    )
    if file_tgts:
        files_addresses = sorted(tgt.address.spec for tgt in file_tgts)
        logger.warning(
            f"The `python_google_cloud_function` target {field_set.address} transitively depends "
            "on the below `files` targets, but Pants will not include them in the built Cloud "
            "Function. Filesystem APIs like `open()` are not able to load files within the binary "
            "itself; instead, they read from the current working directory."
            f"\n\nInstead, use `resources` targets. See {doc_url('resources')}."
            f"\n\nFiles targets dependencies: {files_addresses}"
        )

    # NB: Lambdex modifies its input pex in-place, so the input file is also the output file.
    result = await Get(
        ProcessResult,
        VenvPexProcess(
            lambdex_pex,
            argv=("build", "-M", "main.py", "-H", "handler", "-e", handler.val, output_filename),
            input_digest=pex_result.digest,
            output_files=(output_filename,),
            description=f"Setting up handler in {output_filename}",
        ),
    )

    extra_log_data: list[tuple[str, str]] = []
    if field_set.runtime.value:
        extra_log_data.append(("Runtime", field_set.runtime.value))
    extra_log_data.extend(("Complete platform", path) for path in complete_platforms)
    # The GCP-facing handler function is always `main.handler` (We pass `-M main.py -H handler` to
    # Lambdex to ensure this), which is the wrapper injected by Lambdex that manages invocation of
    # the actual user-supplied handler function. This arrangement works well since GCF assumes the
    # handler function is housed in `main.py` in the root of the zip (you can re-direct this by
    # setting a `GOOGLE_FUNCTION_SOURCE` Google Cloud build environment variable; e.g.:
    # `gcloud functions deploy {--build-env-vars-file,--set-build-env-vars}`, but it's non-trivial
    # to do this right or with intended effect) and the handler name you configure GCF with is just
    # the unqualified function name, which we log here.
    extra_log_data.append(("Handler", "handler"))

    first_column_width = 4 + max(len(header) for header, _ in extra_log_data)
    artifact = BuiltPackageArtifact(
        output_filename,
        extra_log_lines=tuple(
            f"{header.rjust(first_column_width, ' ')}: {data}" for header, data in extra_log_data
        ),
    )
    return BuiltPackage(digest=result.output_digest, artifacts=(artifact,))


def rules():
    return [
        *collect_rules(),
        UnionRule(PackageFieldSet, PythonGoogleCloudFunctionFieldSet),
        *pex_from_targets.rules(),
    ]
