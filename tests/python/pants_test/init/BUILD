# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


python_tests(
  sources=rglobs('*.py'),
  dependencies = [
    '3rdparty/python:future',
    '3rdparty/python:mock',
    '3rdparty/python:parameterized',
    '3rdparty/python:pex',
    '3rdparty/python:setuptools',
    'src/python/pants/base:exceptions',
    'src/python/pants/bin',
    'src/python/pants/build_graph',
    'src/python/pants/engine:rules',
    'src/python/pants/engine:selectors',
    'src/python/pants/goal',
    'src/python/pants/goal:task_registrar',
    'src/python/pants/init',
    'src/python/pants/option',
    'src/python/pants/pantsd:pants_daemon',
    'src/python/pants/subsystem',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'src/python/pants/util:objects',
    'tests/python/pants_test:test_base',
    'tests/python/pants_test/subsystem:subsystem_utils'
  ],
  coverage = ['pants.init'],
)
