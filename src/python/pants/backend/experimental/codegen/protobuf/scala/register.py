# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from pants.backend.codegen import export_codegen_goal
from pants.backend.codegen.protobuf import protobuf_dependency_inference
from pants.backend.codegen.protobuf import target_types as protobuf_target_types
from pants.backend.codegen.protobuf.scala import rules as scala_protobuf_rules
from pants.backend.codegen.protobuf.target_types import (
    ProtobufSourcesGeneratorTarget,
    ProtobufSourceTarget,
)
from pants.backend.scala import target_types as scala_target_types
from pants.backend.scala.compile.scalac import rules as scalac_rules
from pants.core.util_rules import config_files, source_files, stripped_source_files
from pants.core.util_rules.external_tool import rules as external_tool_rules
from pants.jvm import classpath
from pants.jvm.jdk_rules import rules as jdk_rules
from pants.jvm.resolve.coursier_fetch import rules as coursier_fetch_rules
from pants.jvm.resolve.coursier_setup import rules as coursier_setup_rules
from pants.jvm.strip_jar import strip_jar
from pants.jvm.util_rules import rules as util_rules


def target_types():
    return [ProtobufSourcesGeneratorTarget, ProtobufSourceTarget]


def rules():
    return [
        *scala_protobuf_rules.rules(),
        *protobuf_target_types.rules(),
        *protobuf_dependency_inference.rules(),
        *export_codegen_goal.rules(),
        # Re-export rules necessary to avoid rule graph errors.
        *config_files.rules(),
        *classpath.rules(),
        *coursier_fetch_rules(),
        *coursier_setup_rules(),
        *external_tool_rules(),
        *source_files.rules(),
        *strip_jar.rules(),
        *scalac_rules(),
        *util_rules(),
        *jdk_rules(),
        *scala_target_types.rules(),
        *stripped_source_files.rules(),
    ]
