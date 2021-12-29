# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from pants.backend.codegen.thrift.target_types import (
    ThriftSourcesGeneratorTarget,
    ThriftSourceTarget,
)
from pants.engine.target import BoolField


class ScroogeFinagleBoolField(BoolField):
    alias = "finagle"
    default = False
    help = "If True, then also generate Finagle classes for services when using Scrooge as the Thrift generator."


def rules():
    return (
        ThriftSourceTarget.register_plugin_field(ScroogeFinagleBoolField),
        ThriftSourcesGeneratorTarget.register_plugin_field(ScroogeFinagleBoolField),
    )
