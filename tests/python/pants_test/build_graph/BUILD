# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name = 'address',
  sources = ['test_address.py'],
  dependencies = [
    'src/python/pants/base:build_root',
    'src/python/pants/build_graph',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'src/python/pants/testutil:test_base',
  ],
)

python_tests(
  name = 'build_configuration',
  sources = ['test_build_configuration.py'],
  dependencies = [
    'src/python/pants/build_graph',
    'src/python/pants/engine:addresses',
    'src/python/pants/engine:rules',
    'src/python/pants/engine:unions',
    'src/python/pants/engine/internals:native',
    'src/python/pants/engine/legacy:structs',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
  ],
)

python_tests(
  name = 'subproject_integration',
  sources = ['test_subproject_integration.py'],
  dependencies = [
    'src/python/pants/testutil:int-test',
  ],
)


python_tests(
  name = 'build_file_aliases',
  sources = ['test_build_file_aliases.py'],
  dependencies = [
    'src/python/pants/build_graph',
    'src/python/pants/testutil/subsystem',
    'src/python/pants/util:frozendict',
  ],
)
