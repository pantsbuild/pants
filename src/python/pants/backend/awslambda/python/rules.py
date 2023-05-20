# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass

from pants.backend.awslambda.python.target_types import (
    PythonAWSLambda,
    PythonAwsLambdaHandlerField,
    PythonAwsLambdaIncludeRequirements,
    PythonAwsLambdaRuntime,
)
from pants.backend.python.util_rules.faas import (
    BuildLambdexRequest,
    BuildPythonFaaSRequest,
    PythonFaaSCompletePlatforms,
    PythonFaaSLayout,
    PythonFaaSLayoutField,
)
from pants.backend.python.util_rules.faas import rules as faas_rules
from pants.core.goals.package import BuiltPackage, OutputPathField, PackageFieldSet
from pants.core.util_rules.environments import EnvironmentField
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PythonAwsLambdaFieldSet(PackageFieldSet):
    required_fields = (PythonAwsLambdaHandlerField,)

    handler: PythonAwsLambdaHandlerField
    include_requirements: PythonAwsLambdaIncludeRequirements
    runtime: PythonAwsLambdaRuntime
    complete_platforms: PythonFaaSCompletePlatforms
    output_path: OutputPathField
    environment: EnvironmentField
    layout: PythonFaaSLayoutField


@rule(desc="Create Python AWS Lambda", level=LogLevel.DEBUG)
async def package_python_awslambda(
    field_set: PythonAwsLambdaFieldSet,
) -> BuiltPackage:
    layout = PythonFaaSLayout(field_set.layout.value)

    if layout is PythonFaaSLayout.LAMBDEX:
        return await Get(
            BuiltPackage,
            BuildLambdexRequest(
                address=field_set.address,
                target_name=PythonAWSLambda.alias,
                complete_platforms=field_set.complete_platforms,
                runtime=field_set.runtime,
                handler=field_set.handler,
                output_path=field_set.output_path,
                include_requirements=field_set.include_requirements.value,
                script_handler=None,
                script_module=None,
                # The AWS-facing handler function is always lambdex_handler.handler, which is the
                # wrapper injected by lambdex that manages invocation of the actual handler.
                handler_log_message="lambdex_handler.handler",
            ),
        )

    return await Get(
        BuiltPackage,
        BuildPythonFaaSRequest(
            address=field_set.address,
            target_name=PythonAWSLambda.alias,
            complete_platforms=field_set.complete_platforms,
            runtime=field_set.runtime,
            handler=field_set.handler,
            layout=layout,
            output_path=field_set.output_path,
            include_requirements=field_set.include_requirements.value,
            # This doesn't matter (just needs to be fixed), but is the default name used by the AWS
            # console when creating a Python lambda, so is as good as any
            # https://docs.aws.amazon.com/lambda/latest/dg/python-handler.html
            reexported_handler_module="lambda_function",
        ),
    )


def rules():
    return [
        *collect_rules(),
        UnionRule(PackageFieldSet, PythonAwsLambdaFieldSet),
        *faas_rules(),
    ]
