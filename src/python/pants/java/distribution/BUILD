# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  sources=[ 'distribution.py' ],
  dependencies=[
    ':resources',
    'src/python/pants/base:revision',
    'src/python/pants/java:util',
    'src/python/pants/subsystem',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:osutil',
  ],
  tags = {"partially_type_checked"},
)

resources(
  name='resources',
  sources=['*.class'],
)
