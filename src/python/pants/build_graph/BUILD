# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


python_library(
  name = 'build_graph',
  sources = globs('*.py'),
  dependencies = [
    '3rdparty/python:six',
    '3rdparty/python/twitter/commons:twitter.common.collections',
    'src/python/pants/base:address',
    'src/python/pants/base:address_lookup_error',
    'src/python/pants/base:addressable',
    'src/python/pants/base:build_file',
    'src/python/pants/base:build_file_aliases',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:parse_context',
    'src/python/pants/base:payload_field',
    'src/python/pants/base:target',
    'src/python/pants/base:target_addressable',
    'src/python/pants/subsystem',
    'src/python/pants/util:memo',
  ]
)
