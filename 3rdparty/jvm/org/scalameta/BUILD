# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

scala_artifact(
    name="semanticdb_jvm_testprojects",
    group="org.scalameta",
    artifact="semanticdb-scalac",
    version="4.8.4",
    crossversion="full",
    resolve="jvm_testprojects"
)

# Note: These following targets must be kept in sync with the requirements in `generate_scala_parser_lockfile_request`.

scala_artifact(
    name="scalameta",
    group="org.scalameta",
    artifact="scalameta",
    version="4.8.10",
    packages=["scala.meta.**"],
    resolve="scala_parser_dev",
)

scala_artifact(
    name="semanticdb_scala-parser",
    group="org.scalameta",
    artifact="semanticdb-scalac",
    version="4.8.10",
    crossversion="full",
    resolve="scala_parser_dev"
)
