# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Generate Python sources from Protocol Buffers (Protobufs).

See https://pants.readme.io/docs/protobuf.
"""

from pants.backend.codegen.protobuf.python import additional_fields
from pants.backend.codegen.protobuf.python.rules import rules as python_rules
from pants.backend.codegen.protobuf.target_types import ProtobufLibrary
from pants.backend.codegen.protobuf.target_types import rules as target_rules
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.build_graph.target import Target as TargetV1


def rules():
    return [*additional_fields.rules(), *python_rules(), *target_rules()]


def target_types():
    return [ProtobufLibrary]


# Dummy v1 target to ensure that v1 tasks can still parse v2 BUILD files.
class LegacyProtobufLibrary(TargetV1):
    def __init__(self, sources=(), dependencies=(), python_compatibility=None, **kwargs):
        super().__init__(**kwargs)


def build_file_aliases():
    return BuildFileAliases(targets={ProtobufLibrary.alias: LegacyProtobufLibrary})
