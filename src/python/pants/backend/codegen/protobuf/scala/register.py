# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Generate Scala sources from Protocol Buffers (Protobufs).

See https://www.pantsbuild.org/docs/protobuf.
"""

from pants.backend.codegen import export_codegen_goal
from pants.backend.codegen.protobuf import protobuf_dependency_inference
from pants.backend.codegen.protobuf import tailor as protobuf_tailor
from pants.backend.codegen.protobuf.scala.rules import rules as scala_rules
from pants.backend.codegen.protobuf.target_types import (
    ProtobufSourcesGeneratorTarget,
    ProtobufSourceTarget,
)
from pants.backend.codegen.protobuf.target_types import rules as protobuf_target_rules
from pants.core.util_rules import stripped_source_files


def rules():
    return [
        *scala_rules(),
        *protobuf_dependency_inference.rules(),
        *protobuf_tailor.rules(),
        *export_codegen_goal.rules(),
        *protobuf_target_rules(),
        *stripped_source_files.rules(),
    ]


def target_types():
    return [ProtobufSourcesGeneratorTarget, ProtobufSourceTarget]
