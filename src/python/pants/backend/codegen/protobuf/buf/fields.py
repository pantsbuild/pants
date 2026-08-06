# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Language-agnostic per-target buf fields.

`BufGenTemplateField` is shared across language backends (Python, Go, JS, ...) — a
single `buf.gen.yaml` typically declares plugins for multiple languages.
"""

from __future__ import annotations

from pants.backend.codegen.protobuf.target_types import (
    ProtobufSourcesGeneratorTarget,
    ProtobufSourceTarget,
)
from pants.engine.target import StringField
from pants.util.strutil import help_text


class BufGenTemplateField(StringField):
    alias = "buf_gen_template"
    default = None
    help = help_text(
        """
        Path to a `buf.gen.yaml` template for this target, overriding
        `[buf].gen_template`. The path is interpreted relative to the BUILD file's
        directory.

        Only consulted when the target opts into buf-based code generation
        via `protobuf_generator='buf'`.
        """
    )


def rules():
    return [
        ProtobufSourceTarget.register_plugin_field(BufGenTemplateField),
        ProtobufSourcesGeneratorTarget.register_plugin_field(
            BufGenTemplateField, as_moved_field=True
        ),
    ]
