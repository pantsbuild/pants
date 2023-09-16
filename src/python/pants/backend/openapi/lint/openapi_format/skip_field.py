# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.openapi.target_types import OpenApiSourceGeneratorTarget, OpenApiSourceTarget
from pants.engine.target import BoolField


class SkipOpenApiFormatField(BoolField):
    alias = "skip_openapi_format"
    default = False
    help = "If true, don't run `openapi-format` on this target's code."


def rules():
    return [
        OpenApiSourceTarget.register_plugin_field(SkipOpenApiFormatField),
        OpenApiSourceGeneratorTarget.register_plugin_field(SkipOpenApiFormatField),
    ]
