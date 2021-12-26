# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from pants.backend.codegen.thrift.target_types import (
    ThriftSourcesGeneratorTarget,
    ThriftSourceTarget,
)
from pants.engine.target import StringField


# TODO: Maybe merge this with the equivalent field defined in protobuf codegen?
class PythonSourceRootField(StringField):
    alias = "python_source_root"
    help = (
        "The source root to generate Python sources under.\n\nIf unspecified, the source root the "
        "`thrift_sources` is under will be used."
    )


def rules():
    return [
        ThriftSourceTarget.register_plugin_field(PythonSourceRootField),
        ThriftSourcesGeneratorTarget.register_plugin_field(PythonSourceRootField),
    ]
