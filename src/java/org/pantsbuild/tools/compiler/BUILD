# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

java_library(name='compiler',
  provides=artifact(
    org='org.pantsbuild.tools.compiler',
    name='java-compiler',
    repo=public,
    publication_metadata=pants_library("""
      A thin wrapper around the system java compiler that adds support for:
      + dependency tracking
      + warning suppression based on regex matches of paths and messages
      + colorized console output
    """)
  ),
  sources=globs('*.java'),
  dependencies=[
    '3rdparty:jansi'
  ]
)

jvm_binary(name='compiler-main',
  main='org.pantsbuild.tools.compiler.Compiler',
  dependencies=[
    ':compiler'
  ]
)
