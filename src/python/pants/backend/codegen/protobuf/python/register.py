# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Generate Python sources from Protocol Buffers (Protobufs).

See https://www.pantsbuild.org/docs/protobuf.
"""

from pants.backend.codegen.protobuf.python import additional_fields, python_protobuf_subsystem
from pants.backend.codegen.protobuf.python.rules import rules as python_rules
from pants.backend.codegen.protobuf.target_types import ProtobufLibrary
from pants.backend.codegen.protobuf.target_types import rules as target_rules


def rules():
    return [
        *additional_fields.rules(),
        *python_protobuf_subsystem.rules(),
        *python_rules(),
        *target_rules(),
    ]


def target_types():
    return [ProtobufLibrary]
