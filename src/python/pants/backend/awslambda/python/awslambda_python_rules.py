# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass

from pants.backend.awslambda.common.awslambda_common_rules import (
    AWSLambdaConfiguration,
    CreatedAWSLambda,
)
from pants.backend.awslambda.python.lambdex import Lambdex
from pants.backend.awslambda.python.targets import PythonAwsLambdaHandler
from pants.backend.python.rules import (
    download_pex_bin,
    importable_python_sources,
    pex,
    pex_from_targets,
)
from pants.backend.python.rules.pex import (
    Pex,
    PexInterpreterConstraints,
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
from pants.engine.addressable import Addresses
from pants.engine.fs import Digest, DirectoriesToMerge
from pants.engine.isolated_process import Process, ProcessResult
from pants.engine.rules import UnionRule, named_rule, subsystem_rule
from pants.engine.selectors import Get
from pants.python.python_setup import PythonSetup
from pants.rules.core import strip_source_roots


@dataclass(frozen=True)
class PythonAwsLambdaConfiguration(AWSLambdaConfiguration):
    required_fields = (PythonAwsLambdaHandler,)

    handler: PythonAwsLambdaHandler


@dataclass(frozen=True)
class LambdexSetup:
    requirements_pex: Pex


@named_rule(desc="Create Python AWS Lambda")
async def create_python_awslambda(
    config: PythonAwsLambdaConfiguration,
    lambdex_setup: LambdexSetup,
    python_setup: PythonSetup,
    subprocess_encoding_environment: SubprocessEncodingEnvironment,
) -> CreatedAWSLambda:
    # TODO: We must enforce that everything is built for Linux, no matter the local platform.
    pex_filename = f"{config.address.target_name}.pex"
    pex_request = TwoStepPexFromTargetsRequest(
        PexFromTargetsRequest(
            addresses=Addresses([config.address]), entry_point=None, output_filename=pex_filename,
        )
    )

    pex_result = await Get[TwoStepPex](TwoStepPexFromTargetsRequest, pex_request)
    merged_input_files = await Get[Digest](
        DirectoriesToMerge(
            directories=(
                pex_result.pex.directory_digest,
                lambdex_setup.requirements_pex.directory_digest,
            )
        )
    )

    # NB: Lambdex modifies its input pex in-place, so the input file is also the output file.
    lambdex_args = ("build", "-e", config.handler.value, pex_filename)
    process = lambdex_setup.requirements_pex.create_execute_request(
        python_setup=python_setup,
        subprocess_encoding_environment=subprocess_encoding_environment,
        pex_path="./lambdex.pex",
        pex_args=lambdex_args,
        input_files=merged_input_files,
        output_files=(pex_filename,),
        description=f"Run Lambdex for {config.address.reference()}",
    )
    result = await Get[ProcessResult](Process, process)
    return CreatedAWSLambda(digest=result.output_directory_digest, name=pex_filename)


@named_rule(desc="Set up lambdex")
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
        UnionRule(AWSLambdaConfiguration, PythonAwsLambdaConfiguration),
        subsystem_rule(Lambdex),
        *download_pex_bin.rules(),
        *importable_python_sources.rules(),
        *pex.rules(),
        *pex_from_targets.rules(),
        *python_native_code.rules(),
        *strip_source_roots.rules(),
        *subprocess_environment.rules(),
    ]
