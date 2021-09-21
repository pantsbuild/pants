# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

java_library(
    dependencies=[
      ":lockfile",
    ],
)

coursier_lockfile(
    name = "lockfile",
    requirements = [],
    sources = [
        "coursier_resolve.lockfile",
    ],
)
