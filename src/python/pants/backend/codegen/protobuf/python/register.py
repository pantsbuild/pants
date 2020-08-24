# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Generate Python sources from Protocol Buffers (Protobufs).

See https://www.pantsbuild.org/docs/protobuf.
"""

from pants.backend.codegen.protobuf.python import additional_fields
from pants.backend.codegen.protobuf.python.rules import rules as python_rules
from pants.backend.codegen.protobuf.target_types import ProtobufLibrary
from pants.backend.codegen.protobuf.target_types import rules as target_rules


def rules():
    return [*additional_fields.rules(), *python_rules(), *target_rules()]


def target_types():
    return [ProtobufLibrary]


raise Exception(
    "The pants.backend.codege.protobuf.python backend is temporarily disabled for this 2.0 alpha "
    "release, due to performance issues. If you require protobuf support, please do not use this "
    "Pants release.  This is a very temporary measure, to allow alpha testing to proceed on other "
    "features. Protobuf support will be fully restored before the 2.0 release."
)
