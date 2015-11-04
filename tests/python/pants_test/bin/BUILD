# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

target(
  name='bin',
  dependencies=[
    ':extension_loader',
    ':goal_runner',
    ':plugin_resolver',
    ':repro',
  ]
)

python_tests(
  name = 'extension_loader',
  sources = ['test_extension_loader.py'],
  dependencies = [
    'src/python/pants/base:exceptions',
    'src/python/pants/build_graph',
    'src/python/pants/goal',
    'src/python/pants/goal:task_registrar',
    'src/python/pants/subsystem',
  ]
)

python_tests(
  name='goal_runner',
  sources=['test_goal_runner.py'],
  dependencies=[
    '3rdparty/python:setuptools',
    'src/python/pants/base:exceptions',
    'src/python/pants/bin',
    'src/python/pants/option',
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


python_tests(
  name='repro',
  sources=['test_repro.py'],
  dependencies=[
    'src/python/pants/bin',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
  ]
)
