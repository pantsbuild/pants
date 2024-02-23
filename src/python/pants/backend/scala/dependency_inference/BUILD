# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_sources(dependencies=[":scala_resources"])
resources(name="scala_resources", sources=["*.scala", "scala_parser.lock"])

python_tests(name="tests", timeout=240)

# Targets for developing on the Scala parser outside of engine rules.
scala_sources(
    name="scala_parser",
    resolve="scala_parser_dev",
    # TODO: Allow the parser files to be formatted and linted.
    skip_scalafmt=True,
    skip_scalafix=True,
)

jvm_artifact(
    name="org.scala-lang_scala-library_2.13.8",
    group="org.scala-lang",
    artifact="scala-library",
    version="2.13.8",
    resolve="scala_parser_dev",
)
