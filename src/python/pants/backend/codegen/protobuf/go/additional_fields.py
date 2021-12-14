# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.codegen.protobuf.target_types import (
    ProtobufSourcesGeneratorTarget,
    ProtobufSourceTarget,
)
from pants.engine.target import BoolField


class GoGrpcGenField(BoolField):
    alias = "go_grpc"
    default = False
    help = (
        "If True, then generate Go gRPC service stubs for the `protobuf_sources` target on which "
        "this is specified."
    )


def rules():
    return [
        ProtobufSourceTarget.register_plugin_field(GoGrpcGenField),
        ProtobufSourcesGeneratorTarget.register_plugin_field(GoGrpcGenField),
    ]
