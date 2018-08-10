# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name='fetchers',
  sources=['test_fetchers.py'],
  dependencies=[
    'contrib/go/src/python/pants/contrib/go/subsystems',
    'tests/python/pants_test/subsystem:subsystem_utils',
    'tests/python/pants_test:test_base',
  ]
)

python_tests(
  name='go_distribution',
  sources=['test_go_distribution.py'],
  dependencies=[
    '3rdparty/python:future',
    'contrib/go/src/python/pants/contrib/go/subsystems',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:process_handler',
    'tests/python/pants_test/subsystem:subsystem_utils',
  ]
)

python_tests(
    name='go_import_meta_tag_reader',
    sources=['test_go_import_meta_tag_reader.py'],
    dependencies=[
      'contrib/go/src/python/pants/contrib/go/subsystems',
    ]
)

python_tests(
  name='integration',
  sources = globs('test_*_integration.py'),
  dependencies=[
    'contrib/go/src/python/pants/contrib/go/subsystems',
    'tests/python/pants_test:int-test',
  ],
  tags={'integration'},
  timeout=180,
)
