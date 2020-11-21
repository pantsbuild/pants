# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.codegen.protobuf.target_types import ProtobufLibrary
from pants.backend.python.target_types import InterpreterConstraintsField
from pants.engine.target import StringField


class ProtobufPythonInterpreterConstraints(InterpreterConstraintsField):
    alias = "python_interpreter_constraints"


class PythonSourceRootField(StringField):
    """The source root to generate Python sources under.

    If unspecified, the source root the protobuf_library is under will be used.
    """

    alias = "python_source_root"


def rules():
    return [
        ProtobufLibrary.register_plugin_field(ProtobufPythonInterpreterConstraints),
        ProtobufLibrary.register_plugin_field(PythonSourceRootField),
    ]
