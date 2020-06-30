# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

target(
  name = 'all_directories',
  dependencies = [
    ':hello_directory',
    ':pants_publish_plugin_directory',
  ],
)

files(
  name='hello_directory',
  sources=['hello/**/*'],
)

files(
  name='pants_publish_plugin_directory',
  sources=['pants_publish_plugin/**/*'],
)
