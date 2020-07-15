# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# An example of a BUILD file in a parent directory which shares source files with targets in
# subdirectories. Pants supports this, although some text editors such as IntelliJ will not allow a
# directory containing source files to be shared across more than one module when imported via the
# Pants IntelliJ plugin.
python_tests(
  name = 'secondary_source_file_owner',
  sources = ['dummies/test_f1.py'],
)

files(
  name = 'build_parsing_directory',
  sources = ['build_parsing/**/*'],
)

files(
  name = 'dummies_directory',
  sources = ['dummies/**/*'],
)

files(
  name = 'timeout_directory',
  sources = ['timeout/**/*'],
)
