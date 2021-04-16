# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library()

python_tests(
  name='tests',
  dependencies=['src/python/pants/engine/internals:fs_test_data'],
  sources=["*_test.py", "!*_integration_test.py"],
  timeout=90,
)

python_integration_tests(
  name='integration_tests',
  uses_pants_run=True,
  dependencies=[
      # Loaded reflectively as a backend in `streaming_workunit_handler_integration_test.py`.
      'testprojects/pants-plugins/src/python/workunit_logger',
  ],
  timeout=120,
)
