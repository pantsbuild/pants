# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.codegen.protobuf.target_types import (
    ProtobufSourcesGeneratorTarget,
    ProtobufSourceTarget,
)
from pants.engine.target import BoolField


class SkipBufFormatField(BoolField):
    alias = "skip_buf_format"
    default = False
    help = "If true, don't run `buf format` on this target's code."


class SkipBufLintField(BoolField):
    alias = "skip_buf_lint"
    default = False
    help = "If true, don't run `buf lint` on this target's code."


def rules():
    return [
        ProtobufSourceTarget.register_plugin_field(SkipBufFormatField),
        ProtobufSourceTarget.register_plugin_field(SkipBufLintField),
        ProtobufSourcesGeneratorTarget.register_plugin_field(SkipBufFormatField),
        ProtobufSourcesGeneratorTarget.register_plugin_field(SkipBufLintField),
    ]
