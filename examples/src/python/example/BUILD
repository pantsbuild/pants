# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

target(
  name = 'all_directories',
  dependencies = [
    ':hello_directory',
    ':pants_publish_plugin_directory',
    ':tensorflow_custom_op_directory',
  ],
)

page(
  name='readme',
  sources=['README.md'],
  links=[
    ':3rdparty_py',
  ]
)

page(
  name='3rdparty_py',
  sources=['3rdparty_py.md'],
)

files(
  name='hello_directory',
  sources=['hello/**/*'],
)

files(
  name='pants_publish_plugin_directory',
  sources=['pants_publish_plugin/**/*'],
)

files(
  name='tensorflow_custom_op_directory',
  sources=['tensorflow_custom_op/**/*'],
  dependencies = [
    'examples/3rdparty:python_directory',
  ],
)
