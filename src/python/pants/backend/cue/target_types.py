# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    MultipleSourcesField,
    Target,
    generate_multiple_sources_field_help_message,
)
from pants.util.strutil import softwrap


class CuePackageSourcesField(MultipleSourcesField):
    default = ("*.cue",)
    help = generate_multiple_sources_field_help_message(
        "Example: `sources=['schema.cue', 'lib/**/*.cue']`"
    )


class CuePackageTarget(Target):
    alias = "cue_package"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        CuePackageSourcesField,
    )
    help = softwrap("cue package help")
