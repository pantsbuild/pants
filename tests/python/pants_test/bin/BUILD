# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name = 'exiter',
  sources = ['test_exiter.py'],
  dependencies = [
    'src/python/pants/bin',
    'src/python/pants/util:contextutil',
    'tests/python/pants_test/option/util',
    'tests/python/pants_test/option:testing',
  ],
)

python_tests(
  name='exe_integration',
  sources=['test_exe_integration.py'],
  dependencies = [
    'tests/python/pants_test:int-test',
  ],
  tags = {'integration'},
)

python_tests(
  name = 'extension_loader',
  sources = ['test_extension_loader.py'],
  dependencies = [
    'src/python/pants/base:exceptions',
    'src/python/pants/bin',
    'src/python/pants/build_graph',
    'src/python/pants/goal',
    'src/python/pants/goal:task_registrar',
    'src/python/pants/subsystem',
    'src/python/pants/task',
  ],
)

python_tests(
  name='goal_runner',
  sources=['test_goal_runner.py'],
  dependencies = [
    '3rdparty/python:pytest',
    'src/python/pants/base:exceptions',
    'src/python/pants/bin',
    'src/python/pants/option',
  ],
)

python_tests(
  name='plugin_resolver',
  sources=['test_plugin_resolver.py'],
  dependencies = [
    '3rdparty/python:pex',
    '3rdparty/python:pytest',
    'src/python/pants/bin',
    'src/python/pants/option',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
  ],
)

python_tests(
  name='repro',
  sources=['test_repro.py'],
  dependencies = [
    ':repro_mixin',
    'src/python/pants/bin',
    'src/python/pants/fs',
    'src/python/pants/util:contextutil',
  ],
)

python_tests(
  name='repro_ignore',
  sources=['test_repro_ignore.py'],
  dependencies = [
    ':repro_mixin',
    'src/python/pants/base:build_root',
    'src/python/pants/bin',
    'src/python/pants/fs',
    'src/python/pants/util:contextutil',
    'tests/python/pants_test/subsystem:subsystem_utils',
  ],
)

python_library(
  name='repro_mixin',
  sources=['repro_mixin.py'],
  dependencies = [
    'src/python/pants/util:dirutil',
  ],
)
