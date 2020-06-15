# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass

from pants.backend.awslambda.common.awslambda_common_rules import (
    AWSLambdaFieldSet,
    CreatedAWSLambda,
)
from pants.backend.awslambda.python.lambdex import Lambdex
from pants.backend.awslambda.python.target_types import (
    PythonAwsLambdaHandler,
    PythonAwsLambdaRuntime,
)
from pants.backend.python.rules import (
    download_pex_bin,
    importable_python_sources,
    pex,
    pex_from_targets,
)
from pants.backend.python.rules.pex import (
    Pex,
    PexInterpreterConstraints,
    PexPlatforms,
    PexRequest,
    PexRequirements,
    TwoStepPex,
)
from pants.backend.python.rules.pex_from_targets import (
    PexFromTargetsRequest,
    TwoStepPexFromTargetsRequest,
)
from pants.backend.python.subsystems import python_native_code, subprocess_environment
from pants.backend.python.subsystems.subprocess_environment import SubprocessEncodingEnvironment
from pants.core.util_rules import strip_source_roots
from pants.engine.addresses import Addresses
from pants.engine.fs import Digest, MergeDigests
from pants.engine.process import Process, ProcessResult
from pants.engine.rules import SubsystemRule, rule
from pants.engine.selectors import Get
from pants.engine.unions import UnionRule
from pants.python.python_setup import PythonSetup


@dataclass(frozen=True)
class PythonAwsLambdaFieldSet(AWSLambdaFieldSet):
    required_fields = (PythonAwsLambdaHandler, PythonAwsLambdaRuntime)

    handler: PythonAwsLambdaHandler
    runtime: PythonAwsLambdaRuntime


@dataclass(frozen=True)
class LambdexSetup:
    requirements_pex: Pex


@rule(desc="Create Python AWS Lambda")
async def create_python_awslambda(
    field_set: PythonAwsLambdaFieldSet,
    lambdex_setup: LambdexSetup,
    python_setup: PythonSetup,
    subprocess_encoding_environment: SubprocessEncodingEnvironment,
) -> CreatedAWSLambda:
    # Lambdas typically use the .zip suffix, so we use that instead of .pex.
    pex_filename = f"{field_set.address.target_name}.zip"
    # We hardcode the platform value to the appropriate one for each AWS Lambda runtime.
    # (Running the "hello world" lambda in the example code will report the platform, and can be
    # used to verify correctness of these platform strings.)
    py_major, py_minor = field_set.runtime.to_interpreter_version()
    platform = f"manylinux2014_x86_64-cp-{py_major}{py_minor}-cp{py_major}{py_minor}"
    # set pymalloc ABI flag - this was removed in python 3.8 https://bugs.python.org/issue36707
    if py_major <= 3 and py_minor < 8:
        platform += "m"
    if (py_major, py_minor) == (2, 7):
        platform += "u"
    pex_request = TwoStepPexFromTargetsRequest(
        PexFromTargetsRequest(
            addresses=Addresses([field_set.address]),
            entry_point=None,
            output_filename=pex_filename,
            platforms=PexPlatforms([platform]),
        )
    )

    pex_result = await Get[TwoStepPex](TwoStepPexFromTargetsRequest, pex_request)
    input_digest = await Get[Digest](
        MergeDigests((pex_result.pex.digest, lambdex_setup.requirements_pex.digest))
    )

    # NB: Lambdex modifies its input pex in-place, so the input file is also the output file.
    lambdex_args = ("build", "-e", field_set.handler.value, pex_filename)
    process = lambdex_setup.requirements_pex.create_process(
        python_setup=python_setup,
        subprocess_encoding_environment=subprocess_encoding_environment,
        pex_path="./lambdex.pex",
        pex_args=lambdex_args,
        input_digest=input_digest,
        output_files=(pex_filename,),
        description=f"Setting up handler in {pex_filename}",
    )
    result = await Get[ProcessResult](Process, process)
    # Note that the AWS-facing handler function is always lambdex_handler.handler, which
    # is the wrapper injected by lambdex that manages invocation of the actual handler.
    return CreatedAWSLambda(
        digest=result.output_digest,
        name=pex_filename,
        runtime=field_set.runtime.value,
        handler="lambdex_handler.handler",
    )


@rule(desc="Set up lambdex")
async def setup_lambdex(lambdex: Lambdex) -> LambdexSetup:
    requirements_pex = await Get[Pex](
        PexRequest(
            output_filename="lambdex.pex",
            requirements=PexRequirements(lambdex.get_requirement_specs()),
            interpreter_constraints=PexInterpreterConstraints(
                lambdex.default_interpreter_constraints
            ),
            entry_point=lambdex.get_entry_point(),
        )
    )
    return LambdexSetup(requirements_pex=requirements_pex,)


def rules():
    return [
        create_python_awslambda,
        setup_lambdex,
        UnionRule(AWSLambdaFieldSet, PythonAwsLambdaFieldSet),
        SubsystemRule(Lambdex),
        *download_pex_bin.rules(),
        *importable_python_sources.rules(),
        *pex.rules(),
        *pex_from_targets.rules(),
        *python_native_code.rules(),
        *strip_source_roots.rules(),
        *subprocess_environment.rules(),
    ]
