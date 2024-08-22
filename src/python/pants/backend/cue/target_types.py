# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass

from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    FieldSet,
    MultipleSourcesField,
    Target,
    generate_multiple_sources_field_help_message,
)
from pants.util.strutil import help_text


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
    help = help_text(
        """
        The `cue_package` target defines a CUE package. Within a module, CUE organizes files grouped
        by package. A package can be defined within the module or externally. Definitions and
        constraints can be split across files within a package, and even organized across
        directories.

        CUE docs: https://cuelang.org/docs/concepts/packages/
        """
    )


@dataclass(frozen=True)
class CueFieldSet(FieldSet):
    required_fields = (CuePackageSourcesField,)

    sources: CuePackageSourcesField
