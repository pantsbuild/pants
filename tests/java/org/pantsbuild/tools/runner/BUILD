# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

junit_tests(
    name = "jar",
    # This test needs to invoke ./pants at the buildroot.
    cwd = get_buildroot(),
    dependencies = [
        "3rdparty:guava",
        "3rdparty:jsr305",
        "3rdparty:junit",
        "src/java/org/pantsbuild/tools/runner:runner-library",
    ],
)
