# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

files(
  name = 'distance_directory',
  sources = rglobs('distance/*'),
)

files(
  name = 'grpcio_directory',
  sources = rglobs('grpcio/*'),
  dependencies = [
    'examples:3rdparty_directory',
  ],
)

files(
  name = 'imports_directory',
  sources = rglobs('imports/*'),
)

files(
  name = 'unpacked_jars_directory',
  sources = rglobs('unpacked_jars/*'),
)

