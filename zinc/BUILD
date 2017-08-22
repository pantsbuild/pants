# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

jvm_binary(
  name='compiler',
  main='org.pantsbuild.zinc.compiler.Main',
  dependencies=[
    'src/scala/org/pantsbuild/zinc/compiler',
  ],
  description='zinc compiler -- the scala compiler in nailgun',
)

jvm_binary(
  name='extractor',
  main='org.pantsbuild.zinc.extractor.Main',
  dependencies=[
    'src/scala/org/pantsbuild/zinc/extractor',
  ],
  description='zinc extractor -- extractor for zinc analysis',
)
