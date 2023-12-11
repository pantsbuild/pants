# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass

from pants.backend.google_cloud_function.python.target_types import (
    PythonGoogleCloudFunction,
    PythonGoogleCloudFunctionHandlerField,
    PythonGoogleCloudFunctionRuntime,
    PythonGoogleCloudFunctionType,
)
from pants.backend.python.util_rules.faas import (
    BuildPythonFaaSRequest,
    PythonFaaSCompletePlatforms,
    PythonFaaSPex3VenvCreateExtraArgsField,
)
from pants.backend.python.util_rules.faas import rules as faas_rules
from pants.core.goals.package import BuiltPackage, OutputPathField, PackageFieldSet
from pants.core.util_rules.environments import EnvironmentField
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PythonGoogleCloudFunctionFieldSet(PackageFieldSet):
    required_fields = (PythonGoogleCloudFunctionHandlerField,)

    handler: PythonGoogleCloudFunctionHandlerField
    runtime: PythonGoogleCloudFunctionRuntime
    complete_platforms: PythonFaaSCompletePlatforms
    pex3_venv_create_extra_args: PythonFaaSPex3VenvCreateExtraArgsField
    type: PythonGoogleCloudFunctionType
    output_path: OutputPathField
    environment: EnvironmentField


@rule(desc="Create Python Google Cloud Function", level=LogLevel.DEBUG)
async def package_python_google_cloud_function(
    field_set: PythonGoogleCloudFunctionFieldSet,
) -> BuiltPackage:
    return await Get(
        BuiltPackage,
        BuildPythonFaaSRequest(
            address=field_set.address,
            target_name=PythonGoogleCloudFunction.alias,
            complete_platforms=field_set.complete_platforms,
            runtime=field_set.runtime,
            handler=field_set.handler,
            pex3_venv_create_extra_args=field_set.pex3_venv_create_extra_args,
            output_path=field_set.output_path,
            include_requirements=True,
            include_sources=True,
            reexported_handler_module=PythonGoogleCloudFunctionHandlerField.reexported_handler_module,
            log_only_reexported_handler_func=True,
        ),
    )


def rules():
    return [
        *collect_rules(),
        UnionRule(PackageFieldSet, PythonGoogleCloudFunctionFieldSet),
        *faas_rules(),
    ]
