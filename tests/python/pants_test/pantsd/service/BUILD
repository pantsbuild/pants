# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name = 'pants_service',
  sources = ['test_pants_service.py'],
  coverage = ['pants.pantsd.service.pants_service'],
  dependencies = [
    'tests/python/pants_test/pantsd:test_deps',
    'src/python/pants/pantsd/service:pants_service'
  ]
)

python_tests(
  name = 'fs_event_service',
  sources = ['test_fs_event_service.py'],
  coverage = ['pants.pantsd.service.fs_event_service'],
  dependencies = [
    'tests/python/pants_test/pantsd:test_deps',
    'src/python/pants/pantsd/service:fs_event_service'
  ]
)

python_tests(
  name = 'pailgun_service',
  sources = ['test_pailgun_service.py'],
  coverage = ['pants.pantsd.service.pailgun_service'],
  dependencies = [
    'tests/python/pants_test/pantsd:test_deps',
    'src/python/pants/pantsd/service:pailgun_service'
  ]
)
