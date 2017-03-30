# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

java_library(
  name='ivy-dependency-update-checker',
  dependencies=[
    '3rdparty:args4j',
    '3rdparty:ivy',
    'src/java/org/pantsbuild/args4j'
  ],
  platform='java7',
  provides=artifact(
    org='org.pantsbuild',
    name='ivy-dependency-update-checker',
    repo=public,
    publication_metadata=pants_library("""
      A command line tool to display Ivy dependency updates.
    """)
  ),
)

jvm_binary(
  name='main',
  basename='ivy-dependency-update-checker',
  main='org.pantsbuild.tools.ivy.DependencyUpdateChecker',
  dependencies=[
    ':ivy-dependency-update-checker',
  ],
  platform='java7',
)
