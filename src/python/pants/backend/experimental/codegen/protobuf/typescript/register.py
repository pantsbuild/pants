# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
"""Generate TypeScript from Protobuf via `buf generate`."""

from pants.backend.codegen.protobuf import protobuf_dependency_inference, tailor
from pants.backend.codegen.protobuf import target_types as protobuf_target_types
from pants.backend.codegen.protobuf.target_types import (
    ProtobufSourcesGeneratorTarget,
    ProtobufSourceTarget,
)
from pants.backend.codegen.protobuf.typescript import buf_rules as typescript_protobuf_rules
from pants.backend.javascript import install_node_package


def target_types():
    return [ProtobufSourcesGeneratorTarget, ProtobufSourceTarget]


def rules():
    return [
        *typescript_protobuf_rules.rules(),
        *install_node_package.rules(),
        *protobuf_target_types.rules(),
        *protobuf_dependency_inference.rules(),
        *tailor.rules(),
    ]
