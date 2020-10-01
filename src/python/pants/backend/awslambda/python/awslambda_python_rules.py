# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import os
from dataclasses import dataclass

from pants.backend.awslambda.common.awslambda_common_rules import (
    AWSLambdaSubsystem,
    AWSLambdaPythonRequest,
)
from pants.backend.awslambda.python.lambdex import Lambdex
from pants.backend.awslambda.python.target_types import (
    PythonAwsLambdaHandler,
    PythonAwsLambdaRuntime,
)
from pants.backend.python.goals.create_python_binary import (
    PythonBinaryFieldSet,
    PythonBinaryImplementation,
    PythonEntryPointWrapper,
    ReducedPythonBinaryFieldSet,
)
from pants.backend.python.goals.create_python_binary import rules as create_python_binary_rules
from pants.backend.python.util_rules import pex_from_targets
from pants.backend.python.util_rules.pex import (
    Pex,
    PexInterpreterConstraints,
    PexPlatforms,
    PexProcess,
    PexRequest,
    PexRequirements,
    TwoStepPex,
)
from pants.backend.python.util_rules.pex_from_targets import (
    PexFromTargetsRequest,
    TwoStepPexFromTargetsRequest,
)
from pants.core.goals.binary import CreatedBinary
from pants.engine.fs import Digest, MergeDigests
from pants.engine.process import ProcessResult
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.unions import UnionRule
from pants.option.global_options import GlobalOptions
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LambdexSetup:
    requirements_pex: Pex


@rule(desc="Create Python AWS Lambda", level=LogLevel.DEBUG)
async def create_python_awslambda(
    request: AWSLambdaPythonRequest,
    lambdex_setup: LambdexSetup,
    global_options: GlobalOptions,
    awslambda: AWSLambdaSubsystem,
) -> CreatedBinary:
    field_set = request.field_set
    reduced_field_set = ReducedPythonBinaryFieldSet.from_real_field_set(field_set)
    handler = (await Get(PythonEntryPointWrapper, ReducedPythonBinaryFieldSet, reduced_field_set)).value

    # Lambdas typically use the .zip suffix, so we use that instead of .pex.
    disambiguated_lambdex_filename = os.path.join(
        field_set.address.spec_path.replace(os.sep, "."), f"{field_set.address.target_name}.zip"
    )
    if global_options.options.pants_distdir_legacy_paths:
        lambdex_filename = f"{field_set.address.target_name}.zip"
        logger.warning(
            f"Writing to the legacy subpath: {lambdex_filename}, which may not be unique. An "
            f"upcoming version of Pants will switch to writing to the fully-qualified subpath: "
            f"{disambiguated_lambdex_filename}. You can effect that switch now (and silence this "
            f"warning) by setting `pants_distdir_legacy_paths = false` in the [GLOBAL] section of "
            f"pants.toml."
        )
    else:
        lambdex_filename = disambiguated_lambdex_filename
    # We hardcode the platform value to the appropriate one for each AWS Lambda runtime.
    # (Running the "hello world" lambda in the example code will report the platform, and can be
    # used to verify correctness of these platform strings.)
    py_major, py_minor = awslambda.python_runtime.to_interpreter_version()
    platform = f"linux_x86_64-cp-{py_major}{py_minor}-cp{py_major}{py_minor}"
    # set pymalloc ABI flag - this was removed in python 3.8 https://bugs.python.org/issue36707
    if py_major <= 3 and py_minor < 8:
        platform += "m"
    # FIXME: 2.7 is not an allowed aws lambda python runtime version!
    # if (py_major, py_minor) == (2, 7):
    #     platform += "u"
    pex_request = TwoStepPexFromTargetsRequest(
        PexFromTargetsRequest(
            addresses=[field_set.address],
            internal_only=False,
            entry_point=None,
            output_filename=lambdex_filename,
            # The platform (containing the interpreter version) will be checked for compatibility
            # with any interpreter constraints declared on the target.
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

    pex_result = await Get(TwoStepPex, TwoStepPexFromTargetsRequest, pex_request)
    input_digest = await Get(
        Digest, MergeDigests((pex_result.pex.digest, lambdex_setup.requirements_pex.digest))
    )

    # NB: Lambdex modifies its input pex in-place, so the input file is also the output file.
    result = await Get(
        ProcessResult,
        PexProcess(
            lambdex_setup.requirements_pex,
            argv=("build", "-e", handler, lambdex_filename),
            input_digest=input_digest,
            output_files=(lambdex_filename,),
            description=f"Setting up handler in {lambdex_filename}",
        ),
    )
    return CreatedBinary(
        digest=result.output_digest,
        binary_name=lambdex_filename,
    )


@rule(desc="Set up lambdex")
async def setup_lambdex(lambdex: Lambdex) -> LambdexSetup:
    requirements_pex = await Get(
        Pex,
        PexRequest(
            output_filename="lambdex.pex",
            internal_only=True,
            requirements=PexRequirements(lambdex.all_requirements),
            interpreter_constraints=PexInterpreterConstraints(lambdex.interpreter_constraints),
            entry_point=lambdex.entry_point,
        ),
    )
    return LambdexSetup(requirements_pex=requirements_pex)


def rules():
    return [
        *collect_rules(),
        *pex_from_targets.rules(),
        *create_python_binary_rules(),
    ]
