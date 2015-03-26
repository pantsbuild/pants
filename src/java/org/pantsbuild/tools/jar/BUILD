# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

java_library(
  name='jar',
  sources=globs('*.java'),
  dependencies=[
    '3rdparty:commons-io',
    '3rdparty:guava',
    '3rdparty:jsr305',
  ],
  provides=artifact(
    org='org.pantsbuild',
    name='jar-tool',
    repo=public,
  ),
)

jvm_binary(
  name='main',
  basename='jar-tool',
  main='org.pantsbuild.tool.jar.Main',
  dependencies=[
    ':jar',
  ]
)
