# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from pants.backend.codegen import export_codegen_goal
from pants.backend.codegen.thrift.apache.java.rules import rules as apache_thrift_java_rules
from pants.backend.codegen.thrift.apache.rules import rules as apache_thrift_rules
from pants.backend.codegen.thrift.rules import rules as thrift_rules
from pants.backend.codegen.thrift.target_types import (
    ThriftSourcesGeneratorTarget,
    ThriftSourceTarget,
)


def target_types():
    return [ThriftSourcesGeneratorTarget, ThriftSourceTarget]


def rules():
    return [
        *thrift_rules(),
        *apache_thrift_rules(),
        *apache_thrift_java_rules(),
        *export_codegen_goal.rules(),
    ]
