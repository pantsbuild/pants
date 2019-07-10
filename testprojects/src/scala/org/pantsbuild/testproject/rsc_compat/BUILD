# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

scala_library()

jar_library(
    name="rsc-compat",
    jars=[scala_jar(org='com.twitter', name='rsc-rules', rev = "0.0.0-780-e57a1c9c")]
)

SEMANTICDB_REV='4.1.1'
jar_library(name = 'semanticdb-scalac',
            jars = [
              jar(org = 'org.scalameta', name = 'semanticdb-scalac_2.12.8', rev = SEMANTICDB_REV),
            ])

jar_library(name = 'semanticdb',
  jars = [
    scala_jar(org = 'org.scalameta', name = 'semanticdb', rev = SEMANTICDB_REV),
  ])