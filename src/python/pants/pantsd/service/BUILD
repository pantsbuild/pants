# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'pants_service',
  sources = ['pants_service.py'],
  dependencies = [
    '3rdparty/python:dataclasses',
    'src/python/pants/util:meta'
  ],
  tags = {"partially_type_checked"},
)

python_library(
  name = 'fs_event_service',
  sources = ['fs_event_service.py'],
  dependencies = [
    ':pants_service',
    'src/python/pants/pantsd:watchman'
  ],
  tags = {"partially_type_checked"},
)

python_library(
  name = 'scheduler_service',
  sources = ['scheduler_service.py'],
  dependencies = [
    '3rdparty/python/twitter/commons:twitter.common.dirutil',
    ':pants_service'
  ],
  tags = {"partially_type_checked"},
)

python_library(
  name = 'store_gc_service',
  sources = ['store_gc_service.py'],
  dependencies = [
    ':pants_service',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = 'tests',
  dependencies = [
    ':store_gc_service',
    'src/python/pants/testutil:test_base',
  ],
  tags = {"partially_type_checked"},
)
