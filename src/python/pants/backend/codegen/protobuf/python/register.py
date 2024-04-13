# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Generate Python sources from Protocol Buffers (Protobufs).

See https://www.pantsbuild.org/docs/protobuf.
"""

from pants.backend.codegen.protobuf import protobuf_dependency_inference
from pants.backend.codegen.protobuf import tailor as protobuf_tailor
from pants.backend.codegen.protobuf.python import (
    additional_fields,
    python_protobuf_module_mapper,
    python_protobuf_subsystem,
)
from pants.backend.codegen.protobuf.python.rules import rules as python_rules
from pants.backend.codegen.protobuf.target_types import (
    ProtobufSourcesGeneratorTarget,
    ProtobufSourceTarget,
)
from pants.backend.codegen.protobuf.target_types import rules as protobuf_target_rules
from pants.backend.python.dependency_inference import module_mapper
from pants.core.util_rules import stripped_source_files


def rules():
    return [
        *additional_fields.rules(),
        *python_protobuf_subsystem.rules(),
        *python_rules(),
        *python_protobuf_module_mapper.rules(),
        *protobuf_dependency_inference.rules(),
        *protobuf_tailor.rules(),
        *protobuf_target_rules(),
        *module_mapper.rules(),
        *stripped_source_files.rules(),
    ]


def target_types():
    return [ProtobufSourcesGeneratorTarget, ProtobufSourceTarget]
