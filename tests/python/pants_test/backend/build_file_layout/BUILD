# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

target(
  name = 'build_file_layout',
  dependencies = [
    ':source_root',
  ]
)

python_tests(
  name = 'source_root',
  sources = ['test_source_root.py'],
  dependencies = [
    '3rdparty/python/twitter/commons:twitter.common.collections',
    'src/python/pants/base:address',
    'src/python/pants/base:addressable',
    'src/python/pants/backend/build_file_layout:source_root',
    'src/python/pants/base:target',
    ]
)