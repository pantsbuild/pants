# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

target(
  name='bin',
  dependencies=[
    ':plugin_resolver',
  ]
)

python_tests(
  name='plugin_resolver',
  sources=['test_plugin_resolver.py'],
  dependencies=[
    '3rdparty/python:pex',
    '3rdparty/python:setuptools',
    'src/python/pants/bin',
    'src/python/pants/option',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
  ]
)
