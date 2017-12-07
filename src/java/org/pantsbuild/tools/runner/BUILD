# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

java_library(
    name = "runner-library",
    platform = "java7",
    provides = artifact(
        name = "pants-runner",
        org = "org.pantsbuild",
        publication_metadata = pants_library("""
      A command line tool for fixing problems with custom classloading and synthetic jar.
    """),
        repo = public,
    ),
    dependencies = [
        "3rdparty:guava",
    ],
)

jvm_binary(
    name = "runner-binary",
    basename = "pants-runner",
    main = "org.pantsbuild.tools.runner.PantsRunner",
    description = """
    A command line tool for fixing problems with custom classloading and synthetic jar.
  """,
    platform = "java7",
    dependencies = [
        ":runner-library",
    ],
)
