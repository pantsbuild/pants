# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_sources(dependencies=[":scala_resources"])
resources(name="scala_resources", sources=["*.scala", "scala_parser.lockfile"])

python_tests(name="tests", timeout=240)

# Targets for developing on the Scala parser outside of engine rules.
scala_sources(
    name="scala_parser",
    compatible_resolves=["scala_parser"],
)
