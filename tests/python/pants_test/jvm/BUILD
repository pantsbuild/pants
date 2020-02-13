# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name='artifact',
  sources=['test_artifact.py'],
  dependencies=[
    'src/python/pants/backend/jvm:artifact',
    'src/python/pants/backend/jvm:repository',
    'src/python/pants/testutil:test_base',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name='test_safeargs',
  sources=['test_safeargs.py'],
  dependencies=[
    'src/python/pants/backend/jvm:argfile'
  ],
  tags = {"partially_type_checked"},
)
