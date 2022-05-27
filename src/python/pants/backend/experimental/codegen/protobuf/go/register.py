# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from pants.backend.codegen import export_codegen_goal
from pants.backend.codegen.protobuf import protobuf_dependency_inference, tailor
from pants.backend.codegen.protobuf import target_types as protobuf_target_types
from pants.backend.codegen.protobuf.go import rules as go_protobuf_rules
from pants.backend.codegen.protobuf.target_types import (
    ProtobufSourcesGeneratorTarget,
    ProtobufSourceTarget,
)


def target_types():
    return [ProtobufSourcesGeneratorTarget, ProtobufSourceTarget]


def rules():
    return [
        *go_protobuf_rules.rules(),
        *protobuf_target_types.rules(),
        *protobuf_dependency_inference.rules(),
        *tailor.rules(),
        *export_codegen_goal.rules(),
    ]
