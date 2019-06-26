# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

jar_library(
  name='ammonite-ops',
  jars=[
    scala_jar(org='com.lihaoyi', name='ammonite-ops', rev='1.1.2'),
  ],
)

BLOOP_REV = '1.3.2+6-a58d9626+20190625-1923'

jar_library(
  name='bloop-frontend',
  jars=[
    scala_jar(org='ch.epfl.scala', name='bloop-frontend', rev=BLOOP_REV),
  ],
)

jar_library(
  name='bloop-json-config',
  jars=[
    scala_jar(org='ch.epfl.scala', name='bloop-config', rev=BLOOP_REV),
  ],
)

jar_library(
  name='bloop-launcher',
  jars=[
    scala_jar(org='ch.epfl.scala', name='bloop-launcher', rev=BLOOP_REV),
  ],
)

jar_library(
  name='spray-json',
  jars=[
    scala_jar(org='io.spray', name='spray-json', rev='1.3.4'),
  ],
)
