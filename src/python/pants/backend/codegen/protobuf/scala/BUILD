# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_sources(dependencies=[":lockfile", ":scala_sources"])
resource(name="lockfile", source="scalapbc.default.lockfile.txt")
resources(name="scala_sources", sources=["*.scala"])

python_tests(name="tests")
