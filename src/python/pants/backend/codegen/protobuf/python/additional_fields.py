# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.codegen.protobuf.target_types import ProtobufLibrary
from pants.backend.python.target_types import PythonInterpreterCompatibility
from pants.engine.target import PluginField


class ProtobufPythonInterpreterCompatibility(PythonInterpreterCompatibility):
    alias = "python_compatibility"


def rules():
    return [PluginField(ProtobufLibrary, ProtobufPythonInterpreterCompatibility)]
