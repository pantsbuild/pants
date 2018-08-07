# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


python_library(
  name='buildozer_util',
  sources=['buildozer_util.py']
)


python_tests(
  name='buildozer',
  sources=['test_buildozer.py'],
  dependencies=[
    '3rdparty/python:future',
    ':buildozer_util',
    'contrib/buildrefactor/src/python/pants/contrib/buildrefactor',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/util:contextutil',
    'tests/python/pants_test/subsystem:subsystem_utils',
    'tests/python/pants_test:task_test_base',
  ]
)


python_tests(
  name='meta_rename',
  sources=['test_meta_rename.py'],
  dependencies=[
    ':buildozer_util',
    'contrib/buildrefactor/src/python/pants/contrib/buildrefactor',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/base:build_environment',
    'tests/python/pants_test/subsystem:subsystem_utils',
    'tests/python/pants_test:task_test_base',
  ]
)


python_tests(
  name='meta_rename_integration',
  sources=['test_meta_rename_integration.py'],
  dependencies=[
    'tests/python/pants_test:int-test',
  ],
  tags={'integration'},
)


python_tests(
  name='buildozer_integration',
  sources=['test_buildozer_integration.py'],
  dependencies=[
    'tests/python/pants_test:int-test',
  ],
  tags={'integration'},
)
