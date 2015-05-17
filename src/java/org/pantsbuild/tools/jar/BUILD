# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

java_library(
  name='jar',
  sources=globs('*.java'),
  dependencies=[
    '3rdparty:args4j',
    '3rdparty:guava',
    '3rdparty:jsr305',
    'src/java/org/pantsbuild/args4j'
  ],
  provides=artifact(
    org='org.pantsbuild',
    name='jar-tool',
    repo=public,
    publication_metadata=pants_library("""
      A command line tool for creating jars given a set of rules.
    """)
  ),
)

jvm_binary(
  name='main',
  basename='jar-tool',
  main='org.pantsbuild.tools.jar.Main',
  dependencies=[
    ':jar',
  ]
)
