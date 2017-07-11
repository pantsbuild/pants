# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


java_library(
  dependencies=[
  ],
  platform='java7',
  provides=artifact(
    org='org.pantsbuild',
    name='custom_javactool_for_testing',
    repo=public,
    publication_metadata=pants_library("""
      A custom version of com.sun.tools.javac.api.JavacTool, useful for testing
      that we can control the javac version that Zinc uses.
    """)
  ),
)
