# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

page(
  name='node_readme',
  sources=['README.md'],
)

files(
  name='examples_directory',
  sources=['examples/**/*'],
  dependencies = [
    '//:3rdparty_directory',
  ],
)

files(
  name='testprojects_directory',
  sources=['testprojects/**/*'],
)
