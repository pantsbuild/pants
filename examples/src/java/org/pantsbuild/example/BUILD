# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

target(
  name = 'all_directories',
  dependencies = [
    ':annotation_directory',
    ':antlr3_directory',
    ':antlr4_directory',
    ':autovalue_directory',
    ':hello_directory',
    ':java_sources_directory',
    ':javac_directory',
    ':jaxb_directory',
    ':make_it_rain_directory',
    ':protobuf_directory',
    ':wire_directory',
    # NB: See `:java_sources_directory` for why we must declare this dependency here.
    'examples/src/scala/org/pantsbuild/example:scala_with_java_sources_directory'
  ],
)

page(
  name='readme',
  source='README.md',
  links=[
    ':3rdparty_jvm',
    ':from_maven',
    ':publish',
    'examples/src/java/org/pantsbuild/example/javac/plugin:readme',
    'examples/src/scala/org/pantsbuild/example:readme',
    'examples/src/scala/org/pantsbuild/example/scalac/plugin:readme',
    'src/docs:build_files',
    'src/docs:first_concepts',
    'src/docs:first_tutorial',
  ]
)

page(
  name='from_maven',
  source='from_maven.md',
  links=[
    ':3rdparty_jvm',
    ':readme',
  ],
)

page(
  name='publish',
  source='publish.md',
  links=[
    'src/docs:dev_tasks_publish_extras',
    'src/docs:howto_plugin',
  ],
)

page(
  name='3rdparty_jvm',
  source='3rdparty_jvm.md',
  links=[
    'src/docs:3rdparty',
  ],
)

page(
  name='page',
  source='page.md',
  dependencies=[
    'src/docs:howto_contribute'
  ]
)

files(
  name = 'annotation_directory',
  sources = ['annotation/**/*'],
  dependencies = [
    'examples/src/antlr/org/pantsbuild/example:exp_directory',
  ],
)

files(
  name = 'antlr3_directory',
  sources = ['antlr3/**/*'],
  dependencies = [
    'examples/src/antlr/org/pantsbuild/example:exp_directory',
  ],
)

files(
  name = 'antlr4_directory',
  sources = ['antlr4/**/*'],
  dependencies = [
    'examples/src/antlr/org/pantsbuild/example:exp_directory',
  ],
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
  name = 'jaxb_directory',
  sources = ['jaxb/**/*'],
  dependencies = [
    'examples/src/resources/org/pantsbuild/example:jaxb_directory',
  ],
)

files(
  name = 'make_it_rain_directory',
  sources = ['make_it_rain/**/*'],
  dependencies = [
    'examples/src/thrift/org/pantsbuild/example:distance_directory',
    'examples/src/thrift/org/pantsbuild/example:precipitation_directory',
  ],
)

files(
  name = 'protobuf_directory',
  sources = ['protobuf/**/*'],
  dependencies = [
    'examples/src/protobuf/org/pantsbuild/example:distance_directory',
    'examples/src/protobuf/org/pantsbuild/example:imports_directory',
    'examples/src/protobuf/org/pantsbuild/example:unpacked_jars_directory',
  ],
)

files(
  name = 'wire_directory',
  sources = ['wire/**/*'],
  dependencies = [
    'examples/src/wire/org/pantsbuild/example:element_directory',
    'examples/src/wire/org/pantsbuild/example:roots_directory',
    'examples/src/wire/org/pantsbuild/example:temperature_directory',
  ],
)
