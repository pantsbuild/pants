# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass

from pants.backend.awslambda.common.awslambda_common_rules import AWSLambdaTarget, CreatedAWSLambda
from pants.backend.awslambda.python.lambdex import Lambdex
from pants.backend.python.rules import (
    download_pex_bin,
    pex,
    pex_from_target_closure,
    prepare_chrooted_python_sources,
)
from pants.backend.python.rules.pex import (
    CreatePex,
    Pex,
    PexInterpreterConstraints,
    PexRequirementConstraints,
    PexRequirements,
)
from pants.backend.python.rules.pex_from_target_closure import CreatePexFromTargetClosure
from pants.backend.python.subsystems import python_native_code, subprocess_environment
from pants.backend.python.subsystems.subprocess_environment import SubprocessEncodingEnvironment
from pants.engine.addressable import Addresses
from pants.engine.fs import Digest, DirectoriesToMerge
from pants.engine.isolated_process import ExecuteProcessRequest, ExecuteProcessResult
from pants.engine.legacy.structs import PythonAWSLambdaAdaptor
from pants.engine.rules import UnionRule, rule, subsystem_rule
from pants.engine.selectors import Get
from pants.python.python_setup import PythonSetup
from pants.rules.core import strip_source_roots


@dataclass(frozen=True)
class LambdexSetup:
    requirements_pex: Pex


@rule(name="Create Python AWS Lambda")
async def create_python_awslambda(
    lambda_tgt_adaptor: PythonAWSLambdaAdaptor,
    lambdex_setup: LambdexSetup,
    python_setup: PythonSetup,
    subprocess_encoding_environment: SubprocessEncodingEnvironment,
) -> CreatedAWSLambda:
    # TODO: We must enforce that everything is built for Linux, no matter the local platform.
    pex_filename = f"{lambda_tgt_adaptor.address.target_name}.pex"
    pex_request = CreatePexFromTargetClosure(
        addresses=Addresses([lambda_tgt_adaptor.address]),
        entry_point=None,
        output_filename=pex_filename,
    )

    pex = await Get[Pex](CreatePexFromTargetClosure, pex_request)
    merged_input_files = await Get[Digest](
        DirectoriesToMerge(
            directories=(pex.directory_digest, lambdex_setup.requirements_pex.directory_digest)
        )
    )

    # NB: Lambdex modifies its input pex in-place, so the input file is also the output file.
    lambdex_args = ("build", "-e", lambda_tgt_adaptor.handler, pex_filename)
    process_request = lambdex_setup.requirements_pex.create_execute_request(
        python_setup=python_setup,
        subprocess_encoding_environment=subprocess_encoding_environment,
        pex_path="./lambdex.pex",
        pex_args=lambdex_args,
        input_files=merged_input_files,
        output_files=(pex_filename,),
        description=f"Run Lambdex for {lambda_tgt_adaptor.address.reference()}",
    )
    result = await Get[ExecuteProcessResult](ExecuteProcessRequest, process_request)
    return CreatedAWSLambda(digest=result.output_directory_digest, name=pex_filename)


@rule(name="Set up lambdex")
async def setup_lambdex(lambdex: Lambdex, python_setup: PythonSetup) -> LambdexSetup:
    requirements_pex = await Get[Pex](
        CreatePex(
            output_filename="lambdex.pex",
            requirements=PexRequirements(requirements=tuple(lambdex.get_requirement_specs())),
            interpreter_constraints=PexInterpreterConstraints(
                constraint_set=tuple(lambdex.default_interpreter_constraints)
            ),
            requirement_constraints=PexRequirementConstraints.create_from_global_setup(
                python_setup
            ),
            entry_point=lambdex.get_entry_point(),
        )
    )
    return LambdexSetup(requirements_pex=requirements_pex,)


def rules():
    return [
        create_python_awslambda,
        setup_lambdex,
        UnionRule(AWSLambdaTarget, PythonAWSLambdaAdaptor),
        subsystem_rule(Lambdex),
        *download_pex_bin.rules(),
        *pex.rules(),
        *pex_from_target_closure.rules(),
        *prepare_chrooted_python_sources.rules(),
        *python_native_code.rules(),
        *strip_source_roots.rules(),
        *subprocess_environment.rules(),
    ]
