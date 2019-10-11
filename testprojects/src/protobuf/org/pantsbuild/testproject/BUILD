# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

target(
  name = 'all_directories',
  dependencies = [
    ':distance_directory',
    ':import_from_buildroot_directory',
    ':proto-ordering_directory',
    ':utf8proto_directory',
  ],
)

files(
  name = 'distance_directory',
  sources = rglobs('distance/*'),
)

files(
  name = 'import_from_buildroot_directory',
  sources = rglobs('import_from_buildroot/*'),
)

files(
  name = 'proto-ordering_directory',
  sources = rglobs('proto-ordering/*'),
)

files(
  name = 'utf8proto_directory',
  sources = rglobs('utf8proto/*'),
)
