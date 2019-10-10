# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

target(
  name = 'all_directories',
  dependencies = [
    ':hello_directory',
    ':useantlr_directory',
    ':usejaxb_directory',
    ':useproto_directory',
    ':useprotoimports_directory',
    ':usethrift_directory',
    ':usewire_directory',
  ],
)

files(
  name = 'hello_directory',
  sources = rglobs('hello/*'),
  dependencies = [
    'examples/src/java/org/pantsbuild/example:hello_directory',
    'examples/src/resources/org/pantsbuild/example:hello_directory',
  ],
)

files(
  name = 'useantlr_directory',
  sources = rglobs('useantlr/*'),
  dependencies = [
    'examples/src/java/org/pantsbuild/example:antlr3_directory',
    'examples/src/java/org/pantsbuild/example:antlr4_directory',
  ],
)

files(
  name = 'usejaxb_directory',
  sources = rglobs('usejaxb/*'),
  dependencies = [
    'examples/src/java/org/pantsbuild/example:jaxb_directory',
    'examples/src/resources/org/pantsbuild/example:jaxb_directory',
  ],
)

files(
  name = 'useproto_directory',
  sources = rglobs('useproto/*'),
  dependencies = [
    'examples/src/protobuf/org/pantsbuild/example:distance_directory',
  ],
)

files(
  name = 'useprotoimports_directory',
  sources = rglobs('useprotoimports/*'),
  dependencies = [
    'examples/src/protobuf/org/pantsbuild/example:imports_directory',
  ],
)

files(
  name = 'usethrift_directory',
  sources = rglobs('usethrift/*'),
  dependencies = [
    'examples/src/thrift/org/pantsbuild/example:distance_directory',
    'examples/src/thrift/org/pantsbuild/example:precipitation_directory',
  ],
)

files(
  name = 'usewire_directory',
  sources = rglobs('usethrift/*'),
  dependencies = [
    'examples/src/wire/org/pantsbuild/example:temperature_directory',
  ],
)
