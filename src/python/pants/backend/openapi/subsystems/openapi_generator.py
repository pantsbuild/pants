# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.core.goals.resolve_helpers import GenerateToolLockfileSentinel
from pants.engine.rules import collect_rules, rule
from pants.engine.unions import UnionRule
from pants.jvm.resolve.jvm_tool import GenerateJvmLockfileFromTool, JvmToolBase


class OpenAPIGenerator(JvmToolBase):
    options_scope = "openapi-generator"
    help = "The OpenAPI Code generator (https://openapi-generator.tech)"

    default_version = "5.4.0"
    default_artifacts = ("org.openapitools:openapi-generator-cli:{version}",)
    default_lockfile_resource = (
        "pants.backend.openapi.subsystems",
        "openapi_generator.default.lockfile.txt",
    )


class OpenAPIGeneratorLockfileSentinel(GenerateToolLockfileSentinel):
    resolve_name = OpenAPIGenerator.options_scope


@rule
async def generate_openapi_generator_lockfile_request(
    _: OpenAPIGeneratorLockfileSentinel, openapi_generator: OpenAPIGenerator
) -> GenerateJvmLockfileFromTool:
    return GenerateJvmLockfileFromTool.create(openapi_generator)


def rules():
    return [
        *collect_rules(),
        UnionRule(GenerateToolLockfileSentinel, OpenAPIGeneratorLockfileSentinel),
    ]
