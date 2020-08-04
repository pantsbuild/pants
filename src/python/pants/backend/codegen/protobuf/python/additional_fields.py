# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.codegen.protobuf.target_types import ProtobufLibrary
from pants.backend.python.target_types import PythonInterpreterCompatibility
from pants.engine.target import StringField


class ProtobufPythonInterpreterCompatibility(PythonInterpreterCompatibility):
    alias = "python_compatibility"


class PythonSourceRootField(StringField):
    """The source root to generate Python sources under.

    If unspecified, the source root the protobuf_library is under will be used.
    """

    alias = "python_source_root"


def rules():
    return [
        ProtobufLibrary.register_plugin_field(ProtobufPythonInterpreterCompatibility),
        ProtobufLibrary.register_plugin_field(PythonSourceRootField),
    ]
