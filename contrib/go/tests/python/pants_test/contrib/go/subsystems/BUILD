# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name='fetchers',
  sources=['test_fetchers.py'],
  dependencies=[
    'contrib/go/src/python/pants/contrib/go/subsystems',
    'src/python/pants/testutil/subsystem',
    'src/python/pants/testutil:test_base',
  ],
  tags = {'partially_type_checked'},
)

python_tests(
  name='go_distribution',
  sources=['test_go_distribution.py'],
  dependencies=[
    'contrib/go/src/python/pants/contrib/go/subsystems',
    'src/python/pants/util:contextutil',
    'src/python/pants/testutil/subsystem',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name='go_import_meta_tag_reader',
  sources=['test_go_import_meta_tag_reader.py'],
  dependencies=[
    'contrib/go/src/python/pants/contrib/go/subsystems',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name='integration',
  sources = ['test_*_integration.py'],
  dependencies=[
    'contrib/go/src/python/pants/contrib/go/subsystems',
    'contrib/go:examples_directory',
    'src/python/pants/testutil:int-test',
  ],
  tags={'integration', 'partially_type_checked'},
  timeout=400,
)
