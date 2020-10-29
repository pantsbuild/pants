# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.codegen.protobuf.target_types import ProtobufLibrary
from pants.backend.python.target_types import (
    InterpreterConstraintsField,
    PythonInterpreterCompatibility,
)
from pants.engine.target import StringField


class ProtobufPythonInterpreterConstraints(InterpreterConstraintsField):
    alias = "python_interpreter_constraints"


class ProtobufPythonInterpreterCompatibility(PythonInterpreterCompatibility):
    """Deprecated in favor of the `python_interpreter_constraints` field."""

    alias = "python_compatibility"
    deprecated_removal_version = "2.2.0.dev0"
    deprecated_removal_hint = (
        "Use the field `python_interpreter_constraints`. The field does not work with bare strings "
        "and expects a list of strings, so replace `python_compatibility='>3.6'` with "
        "`python_interpreter_constraints=['>3.6']`."
    )


class PythonSourceRootField(StringField):
    """The source root to generate Python sources under.

    If unspecified, the source root the protobuf_library is under will be used.
    """

    alias = "python_source_root"


def rules():
    return [
        ProtobufLibrary.register_plugin_field(ProtobufPythonInterpreterConstraints),
        ProtobufLibrary.register_plugin_field(ProtobufPythonInterpreterCompatibility),
        ProtobufLibrary.register_plugin_field(PythonSourceRootField),
    ]
