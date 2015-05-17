# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

java_library(
  name='withretry',
  provides=artifact(
    org='org.pantsbuild',
    name='junit-runner-withretry',
    repo=public,
    publication_metadata=pants_library("""
      Provides an org.junit.runner.Runner that supports retries of failing tests.
    """)
  ),
  dependencies=[
    '3rdparty:junit',
  ],
  sources=globs('*.java')
)
