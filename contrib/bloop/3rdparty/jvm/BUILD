# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

jar_library(
  name='ammonite-ops',
  jars=[
    scala_jar(org='com.lihaoyi', name='ammonite-ops', rev='1.1.2'),
  ],
)

SCALAMETA_EXCLUDES = [
  exclude(org='org.scalameta'),
  exclude(org='io.circe'),
]

# BLOOP_REV = '1.3.2+0-e473d887+20190618-0608'
BLOOP_REV = '1.3.2'


jar_library(
  name='bloop-frontend',
  jars=[
    scala_jar(org='ch.epfl.scala', name='bloop-frontend', rev=BLOOP_REV,
              # excludes=SCALAMETA_EXCLUDES,
              ),
    # scala_jar(org='ch.epfl.scala', name='compiler-bridge', rev='1.3.0'),
    # scala_jar(org='ch.epfl.scala', name='zinc-classpath', rev='1.3.0'),
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
    scala_jar(org='ch.epfl.scala', name='bloop-launcher', rev=BLOOP_REV,
              # excludes=SCALAMETA_EXCLUDES + [
              #   exclude('ch.epfl.scala', 'bloop-frontend'),
              # ],
              ),
  ],
)

# jar_library(
#   name='bsp4s',
#   jars=[
#     scala_jar(org='ch.epfl.scala', name='bsp4s', rev='2.0.0-M4+1-7c5dbafb',
#               # excludes=SCALAMETA_EXCLUDES,
#               ),
#   ],
# )

# jar_library(
#   name='circe',
#   jars=[
#     scala_jar(org='io.circe', name='circe-core', rev='0.9.0',
#               excludes=[exclude('io.circe', 'circe-derivation')]),
#     scala_jar(org='io.circe', name='circe-derivation', rev='0.9.0-M3'),
#   ],
# )

# jar_library(
#   name='lsp4s',
#   jars=[
#     scala_jar(org='ch.epfl.scala', name='lsp4s', rev='1.2.3',
#               excludes=[exclude(org='io.circe')]),
#   ],
# )

# jar_library(
#   name='monix',
#   jars=[
#     scala_jar(org='io.monix', name='monix', rev='2.3.3',
#               excludes=[exclude(org='io.circe')]),
#     scala_jar(org='io.monix', name='monix-reactive', rev='2.3.3',
#               excludes=[exclude(org='io.circe')]),
#   ],
# )

# jar_library(
#   name='scalameta',
#   jars=[
#     scala_jar(org='org.scalameta', name='scalameta', rev='4.0.0-M2',
#               excludes=[exclude(org='io.circe')]),
#   ],
# )

jar_library(
  name='spray-json',
  jars=[
    scala_jar(org='io.spray', name='spray-json', rev='1.3.4'),
  ],
)
