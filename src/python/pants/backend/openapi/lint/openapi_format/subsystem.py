# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass

from pants.backend.javascript.subsystems.nodejs_tool import NodeJSToolBase
from pants.backend.openapi.lint.openapi_format.skip_field import SkipOpenApiFormatField
from pants.backend.openapi.target_types import OpenApiSourceField
from pants.engine.target import FieldSet, Target
from pants.option.option_types import ArgsListOption, SkipOption


@dataclass(frozen=True)
class OpenApiFormatFieldSet(FieldSet):
    required_fields = (OpenApiSourceField,)
    source: OpenApiSourceField

    @classmethod
    def opt_out(cls, tgt: Target) -> bool:
        return tgt.get(SkipOpenApiFormatField).value


class OpenApiFormatSubsystem(NodeJSToolBase):
    options_scope = "openapi-format"
    name = "openapi-format"
    help = "Format an OpenAPI document by ordering, formatting and filtering fields (https://github.com/thim81/openapi-format)."

    default_version = "openapi-format@1.13.1"

    skip = SkipOption("fmt", "lint")
    args = ArgsListOption(example="--no-sort")
