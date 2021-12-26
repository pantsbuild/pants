# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from pants.backend.codegen.protobuf import protobuf_dependency_inference
from pants.backend.codegen.protobuf import target_types as protobuf_target_types
from pants.backend.codegen.protobuf.go import rules as go_protobuf_rules
from pants.backend.codegen.protobuf.target_types import (
    ProtobufSourcesGeneratorTarget,
    ProtobufSourceTarget,
)
from pants.backend.go.util_rules import sdk


def target_types():
    return [ProtobufSourcesGeneratorTarget, ProtobufSourceTarget]


def rules():
    return [
        *go_protobuf_rules.rules(),
        *protobuf_target_types.rules(),
        *protobuf_dependency_inference.rules(),
        *sdk.rules(),
    ]
