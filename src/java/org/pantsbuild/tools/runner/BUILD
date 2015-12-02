# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

java_library(
  name='runner-library',
  provides=artifact(
    org='org.pantsbuild',
    name='pants-runner',
    repo=public,
    publication_metadata=pants_library("""
      A command line tool for injecting a classpath read from a file into the system classpath.
    """)
  ),
  dependencies=[
    # DO NOT ADD ANY DEPS.
  ],
  sources=globs('*.java')
)

jvm_binary(
  name='runner-binary',
  basename='pants-runner',
  main='org.pantsbuild.tools.runner.FileClassPathRunner',
  dependencies=[
    ':runner-library',
  ],
  description="""
    A command line tool for injecting a classpath read from a file into the system classpath.
  """
)
