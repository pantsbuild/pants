# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

target(
    dependencies = [
        ":eight",
        ":eight-test-platform",
        ":seven",
        ":six",
    ],
)

junit_tests(
    name = "six",
    sources = ["TestSix.java"],
    platform = "java6",
    strict_deps = False,
    dependencies = [":base"],
)

junit_tests(
    name = "seven",
    sources = ["TestSeven.java"],
    platform = "java7",
    strict_deps = False,
    dependencies = [":base"],
)

junit_tests(
    name = "eight",
    sources = ["TestEight.java"],
    platform = "java8",
    strict_deps = False,
    dependencies = [":base"],
)

junit_tests(
    name = "eight-test-platform",
    sources = ["TestEight.java"],
    platform = "java7",
    strict_deps = False,
    test_platform = "java8",
    dependencies = [":base"],
)

java_library(
    name = "base",
    sources = ["TestBase.java"],
    platform = "java6",
    dependencies = ["3rdparty:junit"],
)
