# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.java.bsp import rules as java_bsp_rules
from pants.backend.java.compile import javac
from pants.backend.java.dependency_inference import java_parser
from pants.backend.java.dependency_inference import rules as dependency_inference_rules
from pants.backend.java.goals import check, tailor
from pants.backend.java.target_types import (
    JavaSourcesGeneratorTarget,
    JavaSourceTarget,
    JunitTestsGeneratorTarget,
    JunitTestTarget,
)
from pants.backend.java.target_types import rules as target_types_rules
from pants.core.util_rules import archive
from pants.jvm import common_rules


def target_types():
    return [
        JavaSourceTarget,
        JavaSourcesGeneratorTarget,
        JunitTestTarget,
        JunitTestsGeneratorTarget,
        *common_rules.target_types(),
    ]


def rules():
    return [
        *javac.rules(),
        *check.rules(),
        *java_parser.rules(),
        *dependency_inference_rules.rules(),
        *tailor.rules(),
        *java_bsp_rules.rules(),
        *archive.rules(),
        *target_types_rules(),
        *common_rules.rules(),
    ]


def build_file_aliases():
    return common_rules.build_file_aliases()
