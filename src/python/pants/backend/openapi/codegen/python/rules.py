# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from pants.backend.openapi.codegen.python import extra_fields, generate, package_mapper
from pants.backend.openapi.util_rules import generator_process, pom_parser


def rules():
    return [
        *generate.rules(),
        *extra_fields.rules(),
        *generator_process.rules(),
        *pom_parser.rules(),
        *package_mapper.rules(),
    ]
