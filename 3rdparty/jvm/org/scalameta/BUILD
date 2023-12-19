# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# Note: This target must be kept in sync with the requirements in `generate_scala_parser_lockfile_request`.
scala_artifact(
    name="scalameta",
    group="org.scalameta",
    artifact="scalameta",
    version="4.8.7",
    packages=["scala.meta.**"],
    resolve="scala_parser_dev",
)

# Note: This target must be kept in sync with the requirements in `semanticdb` rules.
scala_artifact(
    name="semanticdb",
    group="org.scalameta",
    artifact="semanticdb-scalac",
    version="4.8.4",
    crossversion="full",
    resolve="scala_parser_dev"
)
