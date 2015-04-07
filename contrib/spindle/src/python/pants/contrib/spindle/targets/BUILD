# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

target(
  name = 'targets',
  dependencies = [
    ':spindle_thrift_library',
  ],
)

python_library(
  name = 'spindle_thrift_library',
  sources = ['spindle_thrift_library.py'],
  dependencies = [
    'src/python/pants/backend/jvm/targets:jvm',
  ],
)
