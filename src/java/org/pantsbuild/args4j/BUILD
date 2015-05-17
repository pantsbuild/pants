# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

java_library(
  name='args4j',
  sources=globs('*.java'),
  dependencies=[
    '3rdparty:args4j',
    '3rdparty:guava',
    '3rdparty:jsr305',
  ],
  provides=artifact(
    org='org.pantsbuild',
    name='args4j',
    repo=public,
    publication_metadata=pants_library("""
      Utilities to make args4j more like com.twitter.common#args
    """)
  ),
)
