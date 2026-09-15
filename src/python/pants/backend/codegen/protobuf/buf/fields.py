# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Per-target buf fields shared by the language backends."""

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
        Path to the `buf.gen.yaml` template for this target, relative to the BUILD
        file's directory. Only used when `protobuf_generator='buf'`.

        A target's template is the first of: this field, the language's
        `buf_gen_template` option (e.g. `[python-protobuf].buf_gen_template`),
        `[buf].gen_template`, and a `buf.gen.yaml` at the repository root.
        """
    )


def rules():
    return [
        ProtobufSourceTarget.register_plugin_field(BufGenTemplateField),
        ProtobufSourcesGeneratorTarget.register_plugin_field(
            BufGenTemplateField, as_moved_field=True
        ),
    ]
