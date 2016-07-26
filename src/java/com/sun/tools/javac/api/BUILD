# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


java_library(
  name='api',
  sources=globs('*.java'),
  dependencies=[
  ],
  # Note that this target requires a JDK8 tools.jar in order to compile.
  # If a higher JDK version is selected then its tools.jar may not be compatible.
  # Unfortunately there's currently no way to require a specific version of the JDK.
  # We can only require a version compatible with a specific language version.
  # In practice, until Java9 is released some time in 2017, this won't be a problem.
  # By then we should have a way of restricting to a specific JDK version.
  platform='java8',
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
