# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

java_library(
  name='runner-library',
  provides=artifact(
    org='org.pantsbuild',
    name='pants-runner',
    repo=public,
    publication_metadata=pants_library("""
      A command line tool for fixing problems with custom classloading and synthetic jar.
    """)
  ),
  dependencies=[
    '3rdparty:guava',
  ],
  sources=globs('*.java')
)
