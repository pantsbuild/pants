# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.codegen.protobuf.target_types import (
    ProtobufSourcesGeneratorTarget,
    ProtobufSourceTarget,
)
from pants.engine.target import BoolField


class SkipBufField(BoolField):
    alias = "skip_buf_lint"
    default = False
    help = "If true, don't lint this target's code with Buf."


def rules():
    return [
        ProtobufSourceTarget.register_plugin_field(SkipBufField),
        ProtobufSourcesGeneratorTarget.register_plugin_field(SkipBufField),
    ]
