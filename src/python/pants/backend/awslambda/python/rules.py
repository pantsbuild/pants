# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass

from pants.backend.awslambda.python.aws_architecture import AWSLambdaArchitectureField
from pants.backend.awslambda.python.target_types import (
    PythonAWSLambda,
    PythonAwsLambdaHandlerField,
    PythonAwsLambdaIncludeRequirements,
    PythonAwsLambdaIncludeSources,
    PythonAWSLambdaLayer,
    PythonAwsLambdaLayerDependenciesField,
    PythonAwsLambdaRuntime,
)
from pants.backend.python.util_rules.faas import (
    BuildPythonFaaSRequest,
    PythonFaaSCompletePlatforms,
    PythonFaaSLayoutField,
    PythonFaaSPex3VenvCreateExtraArgsField,
    PythonFaaSPexBuildExtraArgs,
)
from pants.backend.python.util_rules.faas import rules as faas_rules
from pants.core.goals.package import BuiltPackage, OutputPathField, PackageFieldSet
from pants.core.util_rules.environments import EnvironmentField
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _BaseFieldSet(PackageFieldSet):
    include_requirements: PythonAwsLambdaIncludeRequirements
    runtime: PythonAwsLambdaRuntime
    complete_platforms: PythonFaaSCompletePlatforms
    pex3_venv_create_extra_args: PythonFaaSPex3VenvCreateExtraArgsField
    pex_build_extra_args: PythonFaaSPexBuildExtraArgs
    layout: PythonFaaSLayoutField
    output_path: OutputPathField
    environment: EnvironmentField


@dataclass(frozen=True)
class PythonAwsLambdaFieldSet(_BaseFieldSet):
    required_fields = (PythonAwsLambdaHandlerField,)

    handler: PythonAwsLambdaHandlerField
    architecture: AWSLambdaArchitectureField


@dataclass(frozen=True)
class PythonAwsLambdaLayerFieldSet(_BaseFieldSet):
    required_fields = (PythonAwsLambdaLayerDependenciesField,)

    dependencies: PythonAwsLambdaLayerDependenciesField
    include_sources: PythonAwsLambdaIncludeSources
    architecture: AWSLambdaArchitectureField


@rule(desc="Create Python AWS Lambda Function", level=LogLevel.DEBUG)
async def package_python_aws_lambda_function(
    field_set: PythonAwsLambdaFieldSet,
) -> BuiltPackage:
    return await Get(
        BuiltPackage,
        BuildPythonFaaSRequest(
            address=field_set.address,
            target_name=PythonAWSLambda.alias,
            complete_platforms=field_set.complete_platforms,
            runtime=field_set.runtime,
            aws_architecture=field_set.architecture,
            handler=field_set.handler,
            output_path=field_set.output_path,
            include_requirements=field_set.include_requirements.value,
            include_sources=True,
            pex3_venv_create_extra_args=field_set.pex3_venv_create_extra_args,
            pex_build_extra_args=field_set.pex_build_extra_args,
            layout=field_set.layout,
            reexported_handler_module=PythonAwsLambdaHandlerField.reexported_handler_module,
        ),
    )


@rule(desc="Create Python AWS Lambda Layer", level=LogLevel.DEBUG)
async def package_python_aws_lambda_layer(
    field_set: PythonAwsLambdaLayerFieldSet,
) -> BuiltPackage:
    return await Get(
        BuiltPackage,
        BuildPythonFaaSRequest(
            address=field_set.address,
            target_name=PythonAWSLambdaLayer.alias,
            complete_platforms=field_set.complete_platforms,
            runtime=field_set.runtime,
            aws_architecture=field_set.architecture,
            output_path=field_set.output_path,
            include_requirements=field_set.include_requirements.value,
            include_sources=field_set.include_sources.value,
            pex3_venv_create_extra_args=field_set.pex3_venv_create_extra_args,
            pex_build_extra_args=field_set.pex_build_extra_args,
            layout=field_set.layout,
            # See
            # https://docs.aws.amazon.com/lambda/latest/dg/configuration-layers.html#configuration-layers-path
            #
            # Runtime | Path
            # ...
            # Python  | `python`
            #         | `python/lib/python3.10/site-packages`
            # ...
            #
            # The one independent on the runtime-version is more convenient:
            prefix_in_artifact="python",
            # a layer doesn't have a handler, just pulls in things via `dependencies`
            handler=None,
            reexported_handler_module=None,
        ),
    )


def rules():
    return [
        *collect_rules(),
        UnionRule(PackageFieldSet, PythonAwsLambdaFieldSet),
        UnionRule(PackageFieldSet, PythonAwsLambdaLayerFieldSet),
        *faas_rules(),
    ]
