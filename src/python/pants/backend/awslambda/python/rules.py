# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass

from pants.backend.awslambda.python.lambdex import Lambdex
from pants.backend.awslambda.python.target_types import (
    PythonAwsLambdaHandlerField,
    PythonAwsLambdaRuntime,
    ResolvedPythonAwsHandler,
    ResolvePythonAwsHandlerRequest,
)
from pants.backend.python.util_rules import pex_from_targets
from pants.backend.python.util_rules.pex import (
    PexInterpreterConstraints,
    PexPlatforms,
    PexRequest,
    PexRequirements,
    TwoStepPex,
    VenvPex,
    VenvPexProcess,
)
from pants.backend.python.util_rules.pex_from_targets import (
    PexFromTargetsRequest,
    TwoStepPexFromTargetsRequest,
)
from pants.core.goals.package import (
    BuiltPackage,
    BuiltPackageArtifact,
    OutputPathField,
    PackageFieldSet,
)
from pants.engine.process import ProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel


@dataclass(frozen=True)
class PythonAwsLambdaFieldSet(PackageFieldSet):
    required_fields = (PythonAwsLambdaHandlerField, PythonAwsLambdaRuntime)

    handler: PythonAwsLambdaHandlerField
    runtime: PythonAwsLambdaRuntime
    output_path: OutputPathField


@rule(desc="Create Python AWS Lambda", level=LogLevel.DEBUG)
async def package_python_awslambda(
    field_set: PythonAwsLambdaFieldSet, lambdex: Lambdex
) -> BuiltPackage:
    output_filename = field_set.output_path.value_or_default(
        field_set.address,
        # Lambdas typically use the .zip suffix, so we use that instead of .pex.
        file_ending="zip",
    )

    # We hardcode the platform value to the appropriate one for each AWS Lambda runtime.
    # (Running the "hello world" lambda in the example code will report the platform, and can be
    # used to verify correctness of these platform strings.)
    py_major, py_minor = field_set.runtime.to_interpreter_version()
    platform = f"linux_x86_64-cp-{py_major}{py_minor}-cp{py_major}{py_minor}"
    # set pymalloc ABI flag - this was removed in python 3.8 https://bugs.python.org/issue36707
    if py_major <= 3 and py_minor < 8:
        platform += "m"
    if (py_major, py_minor) == (2, 7):
        platform += "u"
    pex_request = TwoStepPexFromTargetsRequest(
        PexFromTargetsRequest(
            addresses=[field_set.address],
            internal_only=False,
            entry_point=None,
            output_filename=output_filename,
            platforms=PexPlatforms([platform]),
            additional_args=[
                # Ensure we can resolve manylinux wheels in addition to any AMI-specific wheels.
                "--manylinux=manylinux2014",
                # When we're executing Pex on Linux, allow a local interpreter to be resolved if
                # available and matching the AMI platform.
                "--resolve-local-platforms",
            ],
        )
    )

    lambdex_request = PexRequest(
        output_filename="lambdex.pex",
        internal_only=True,
        requirements=PexRequirements(lambdex.all_requirements),
        interpreter_constraints=PexInterpreterConstraints(lambdex.interpreter_constraints),
        entry_point=lambdex.entry_point,
    )

    lambdex_pex, pex_result, handler = await MultiGet(
        Get(VenvPex, PexRequest, lambdex_request),
        Get(TwoStepPex, TwoStepPexFromTargetsRequest, pex_request),
        Get(ResolvedPythonAwsHandler, ResolvePythonAwsHandlerRequest(field_set.handler)),
    )

    # NB: Lambdex modifies its input pex in-place, so the input file is also the output file.
    result = await Get(
        ProcessResult,
        VenvPexProcess(
            lambdex_pex,
            argv=("build", "-e", handler.val, output_filename),
            input_digest=pex_result.pex.digest,
            output_files=(output_filename,),
            description=f"Setting up handler in {output_filename}",
        ),
    )
    artifact = BuiltPackageArtifact(
        output_filename,
        extra_log_lines=(
            f"    Runtime: {field_set.runtime.value}",
            # The AWS-facing handler function is always lambdex_handler.handler, which is the
            # wrapper injected by lambdex that manages invocation of the actual handler.
            "    Handler: lambdex_handler.handler",
        ),
    )
    return BuiltPackage(digest=result.output_digest, artifacts=(artifact,))


def rules():
    return [
        *collect_rules(),
        UnionRule(PackageFieldSet, PythonAwsLambdaFieldSet),
        *pex_from_targets.rules(),
    ]
