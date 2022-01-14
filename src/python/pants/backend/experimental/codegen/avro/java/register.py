# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from pants.backend.codegen.avro.java.rules import rules as avro_java_rules
from pants.backend.codegen.avro.rules import rules as avro_rules
from pants.backend.codegen.avro.target_types import AvroSourcesGeneratorTarget, AvroSourceTarget
from pants.core.util_rules import config_files, source_files, stripped_source_files
from pants.core.util_rules.external_tool import rules as external_tool_rules
from pants.jvm import classpath
from pants.jvm.compile import rules as jvm_compile_rules
from pants.jvm.jdk_rules import rules as jdk_rules
from pants.jvm.resolve.coursier_fetch import rules as coursier_fetch_rules
from pants.jvm.resolve.coursier_setup import rules as coursier_setup_rules
from pants.jvm.util_rules import rules as util_rules


def target_types():
    return [AvroSourcesGeneratorTarget, AvroSourceTarget]


def rules():
    return [
        *avro_rules(),
        *avro_java_rules(),
        # Re-export rules necessary to avoid rule graph errors.
        *config_files.rules(),
        *classpath.rules(),
        *coursier_fetch_rules(),
        *coursier_setup_rules(),
        *external_tool_rules(),
        *source_files.rules(),
        *util_rules(),
        *jdk_rules(),
        *stripped_source_files.rules(),
        *jvm_compile_rules(),
    ]
