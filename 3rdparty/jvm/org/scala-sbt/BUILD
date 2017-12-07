# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

jar_library(
    name = "zinc",
    jars = [
        scala_jar(
            name = "zinc",
            org = "org.scala-sbt",
            rev = "1.0.3",
            excludes = [
                exclude(
                    name = "io_2.11",
                    org = "org.scala-sbt",
                ),
                exclude(
                    name = "util-logging_2.11",
                    org = "org.scala-sbt",
                ),
            ],
        ),
    ],
    dependencies = [
        ":io",
        ":util-logging",
    ],
)

jar_library(
    name = "util-logging",
    jars = [
        # TODO: `zinc` only declares a dep on the `tests` classifier for
        # util-logging for some reason. We redefine the dep here to get the full package.
        scala_jar(
            name = "util-logging",
            force = True,
            org = "org.scala-sbt",
            rev = "1.0.0",
        ),
    ],
)

jar_library(
    name = "io",
    jars = [
        # TODO: `zinc` only declares a dep on the `tests` classifier for
        # io. We redefine the dep here to get the full package.
        scala_jar(
            name = "io",
            force = True,
            org = "org.scala-sbt",
            rev = "1.0.0",
        ),
    ],
)
