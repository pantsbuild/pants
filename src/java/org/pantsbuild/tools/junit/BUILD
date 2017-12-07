# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

java_library(
    sources = globs("*.java", "impl/*.java", "impl/experimental/*.java"),
    platform = "java7",
    provides = artifact(
        name = "junit-runner",
        org = "org.pantsbuild",
        publication_metadata = pants_library("""
      A command line tool for running junit tests that provides functionality above and beyond
      that provided by org.junit.runner.JUnitCore.
    """),
        repo = public,
    ),
    dependencies = [
        "3rdparty:args4j",
        "3rdparty:guava",
        "3rdparty:junit",
        "3rdparty/jvm/commons-io",
        "src/java/org/pantsbuild/args4j",
        "src/java/org/pantsbuild/junit/annotations",
        "src/java/org/pantsbuild/tools/junit/withretry",
    ],
)

jvm_binary(
    name = "main",
    basename = "junit-runner",
    main = "org.pantsbuild.tools.junit.ConsoleRunner",
    description = """
A replacement for org.junit.runner.JUnitCore.main that adds:
  + support for running individual test methods using [classname]#[methodname]
  + support for stderr and stdout redirection for tests
  + support for ant style junit-report xml output
  + support for per test class timer
  + support for running test classes in parallel
""",
    platform = "java7",
    dependencies = [
        ":junit",
    ],
)
