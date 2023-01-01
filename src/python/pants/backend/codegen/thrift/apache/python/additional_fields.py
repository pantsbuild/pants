# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.codegen.thrift.target_types import (
    ThriftSourcesGeneratorTarget,
    ThriftSourceTarget,
)
from pants.backend.python.target_types import PythonResolveField


class ThriftPythonResolveField(PythonResolveField):
    alias = "python_resolve"


def rules():
    return [
        ThriftSourceTarget.register_plugin_field(ThriftPythonResolveField),
        ThriftSourcesGeneratorTarget.register_plugin_field(ThriftPythonResolveField),
    ]
