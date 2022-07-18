# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from pants.backend.codegen import export_codegen_goal
from pants.backend.codegen.thrift.rules import rules as thrift_rules
from pants.backend.codegen.thrift.scrooge.java.rules import rules as scrooge_java_rules
from pants.backend.codegen.thrift.scrooge.rules import rules as scrooge_rules
from pants.backend.codegen.thrift.target_types import (
    ThriftSourcesGeneratorTarget,
    ThriftSourceTarget,
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
    return [ThriftSourcesGeneratorTarget, ThriftSourceTarget]


def rules():
    return [
        *thrift_rules(),
        *scrooge_rules(),
        *scrooge_java_rules(),
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
