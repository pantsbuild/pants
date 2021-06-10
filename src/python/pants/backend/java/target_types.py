# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.engine.target import COMMON_TARGET_FIELDS, Dependencies, Sources, Target


class JavaSources(Sources):
    expected_file_extensions = (".java",)


class JavaTestsSources(JavaSources):
    default = ("*Test.java",)


class JunitTests(Target):
    alias = "junit_tests"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        Dependencies,
        JavaTestsSources,
    )
    help = "Java tests, run with Junit."


class JavaLibrarySources(JavaSources):
    default = ("*.java",) + tuple(f"!{pat}" for pat in JavaTestsSources.default)


class JavaLibrary(Target):
    alias = "java_library"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        Dependencies,
        JavaLibrarySources,
    )
    help = "Java source code."
