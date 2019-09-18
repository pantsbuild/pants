# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

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
  name = 'antlr3_directory',
  sources = rglobs('antlr3/*'),
  dependencies = [
    'examples/src/antlr/org/pantsbuild/example:exp_directory',
  ],
)

files(
  name = 'antlr4_directory',
  sources = rglobs('antlr4/*'),
  dependencies = [
    'examples/src/antlr/org/pantsbuild/example:exp_directory',
  ],
)

files(
  name = 'autovalue_directory',
  sources = rglobs('autovalue/*'),
)

files(
  name = 'hello_directory',
  sources = rglobs('hello/*'),
  dependencies = [
    'examples/src/resources/org/pantsbuild/example:hello_directory',
  ],
)

files(
  name = 'javac_directory',
  sources = rglobs('javac/*'),
)

files(
  name = 'protobuf_directory',
  sources = rglobs('protobuf/*'),
  dependencies = [
    'examples/src/protobuf/org/pantsbuild/example:distance_directory',
    'examples/src/protobuf/org/pantsbuild/example:imports_directory',
    'examples/src/protobuf/org/pantsbuild/example:unpacked_jars_directory',
  ],
)

files(
  name = 'wire_directory',
  sources = rglobs('wire/*'),
  dependencies = [
    'examples/src/wire/org/pantsbuild/example:element_directory',
    'examples/src/wire/org/pantsbuild/example:roots_directory',
    'examples/src/wire/org/pantsbuild/example:temperature_directory',
  ],
)
