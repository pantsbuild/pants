# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# Note: These following targets must be kept in sync with the requirements in `generate_scala_parser_lockfile_request`.

SCALAMETA_GROUP = "org.scalameta"
SCALAMETA_VERSION = "4.8.14"

scala_artifact(
    name="scalameta",
    group=SCALAMETA_GROUP,
    artifact="scalameta",
    version=SCALAMETA_VERSION,
    packages=["scala.meta.**"],
    resolve="scala_parser_dev",
)

scala_artifact(
    name="semanticdb_scala-parser",
    group=SCALAMETA_GROUP,
    artifact="semanticdb-scalac",
    version=SCALAMETA_VERSION,
    crossversion="full",
    resolve=parametrize("jvm_testprojects", "scala_parser_dev")
)
