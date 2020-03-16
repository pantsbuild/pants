# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

target(
  name = 'all_directories',
  dependencies = [
    ':fact_directory',
    ':hello_directory',
    ':jvm_run_directory',
    ':scala_with_java_sources_directory',
    ':scalac_directory',
    ':several_scala_targets_directory',
    ':styleissue_directory',
  ],
)

page(
  name = 'readme',
  sources = ['README.md'],
  links = [
    'examples/src/java/org/pantsbuild/example:readme',
  ],
)

files(
  name = 'fact_directory',
  sources = ['fact/**/*'],
)

files(
  name = 'hello_directory',
  sources = ['hello/**/*'],
  dependencies = [
    'examples/src/java/org/pantsbuild/example:hello_directory',
    'examples/src/resources/org/pantsbuild/example:hello_directory',
  ],
)

files(
  name = 'jvm_run_directory',
  sources = ['jvm_run/**/*'],
  dependencies = [
    ':hello_directory',
  ],
)

files(
  name = 'scala_with_java_sources_directory',
  sources = ['scala_with_java_sources/**/*'],
  dependencies = [
    'examples/src/java/org/pantsbuild/example:java_sources_directory',
  ],
)

files(
  name = 'scalac_directory',
  sources = ['scalac/**/*'],
)

files(
  name = 'several_scala_targets_directory',
  sources = ['several_scala_targets/**/*'],
)

files(
  name = 'styleissue_directory',
  sources = ['styleissue/**/*'],
)
