# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.openapi.target_types import OpenApiDocumentGeneratorTarget, OpenApiDocumentTarget
from pants.engine.target import BoolField


class SkipSpectralField(BoolField):
    alias = "skip_spectral"
    default = False
    help = "If true, don't run `spectral lint` on this target's code."


def rules():
    return [
        OpenApiDocumentTarget.register_plugin_field(SkipSpectralField),
        OpenApiDocumentGeneratorTarget.register_plugin_field(SkipSpectralField),
    ]
