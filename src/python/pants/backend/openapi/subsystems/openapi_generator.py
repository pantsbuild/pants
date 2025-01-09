# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.core.goals.resolves import ExportableTool
from pants.engine.rules import collect_rules
from pants.engine.unions import UnionRule
from pants.jvm.resolve.jvm_tool import JvmToolBase


class OpenAPIGenerator(JvmToolBase):
    options_scope = "openapi-generator"
    help = "The OpenAPI Code generator (https://openapi-generator.tech)"

    default_version = "5.4.0"
    default_artifacts = ("org.openapitools:openapi-generator-cli:{version}",)
    default_lockfile_resource = (
        "pants.backend.openapi.subsystems",
        "openapi_generator.default.lockfile.txt",
    )


def rules():
    return [
        *collect_rules(),
        UnionRule(ExportableTool, OpenAPIGenerator),
    ]
