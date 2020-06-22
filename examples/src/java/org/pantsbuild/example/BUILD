# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

target(
  name = 'all_directories',
  dependencies = [
    ':annotation_directory',
    ':autovalue_directory',
    ':hello_directory',
    ':java_sources_directory',
    ':javac_directory',
    ':make_it_rain_directory',
    # NB: See `:java_sources_directory` for why we must declare this dependency here.
    'examples/src/scala/org/pantsbuild/example:scala_with_java_sources_directory'
  ],
)

files(
  name = 'annotation_directory',
  sources = ['annotation/**/*'],
)

files(
  name = 'autovalue_directory',
  sources = ['autovalue/**/*'],
)

files(
  name = 'hello_directory',
  sources = ['hello/**/*'],
  dependencies = [
    'examples/src/resources/org/pantsbuild/example:hello_directory',
  ],
)

# NB: This has an undeclared dependency on
# `examples/src/scala/org/pantsbuild/example:scala_with_java_sources_directory`. We do not declare
# it here because it would cause a dep cycle. Instead, we hack around this by declaring the
# dependency in `all_targets` to get this working with the testprojects integration test.
files(
  name = 'java_sources_directory',
  sources = ['java_sources/**/*'],
)

files(
  name = 'javac_directory',
  sources = ['javac/**/*'],
)

files(
  name = 'make_it_rain_directory',
  sources = ['make_it_rain/**/*'],
  dependencies = [
    'examples/src/thrift/org/pantsbuild/example:distance_directory',
    'examples/src/thrift/org/pantsbuild/example:precipitation_directory',
  ],
)
