# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.java.compile import javac
from pants.backend.java.dependency_inference import java_parser
from pants.backend.java.dependency_inference import rules as dependency_inference_rules
from pants.backend.java.goals import check, tailor
from pants.backend.java.target_types import (
    JavaSourceField,
    JavaSourcesGeneratorTarget,
    JavaSourceTarget,
    JunitTestsGeneratorTarget,
    JunitTestTarget,
)
from pants.backend.java.target_types import rules as target_types_rules
from pants.core.util_rules import archive
from pants.core.util_rules.wrap_source import wrap_source_rule_and_target
from pants.jvm import jvm_common

wrap_java = wrap_source_rule_and_target(JavaSourceField, "java_sources")


def target_types():
    return [
        JavaSourceTarget,
        JavaSourcesGeneratorTarget,
        JunitTestTarget,
        JunitTestsGeneratorTarget,
        *jvm_common.target_types(),
        *wrap_java.target_types,
    ]


def rules():
    return [
        *javac.rules(),
        *check.rules(),
        *java_parser.rules(),
        *dependency_inference_rules.rules(),
        *tailor.rules(),
        *archive.rules(),
        *target_types_rules(),
        *jvm_common.rules(),
        *wrap_java.rules,
    ]


def build_file_aliases():
    return jvm_common.build_file_aliases()
