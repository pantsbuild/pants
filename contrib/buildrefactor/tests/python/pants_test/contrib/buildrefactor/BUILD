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
    'contrib/buildrefactor/src/python/pants/contrib/buildrefactor:buildozer',
    'contrib/buildrefactor/tests/python/pants_test/contrib/buildrefactor:buildozer_util',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/util:contextutil',
    'tests/python/pants_test/subsystem:subsystem_utils',
    'tests/python/pants_test/tasks:task_test_base',
  ]
)


python_tests(
  name='meta_rename',
  sources=['test_meta_rename.py'],
  dependencies=[
    'contrib/buildrefactor/src/python/pants/contrib/buildrefactor:buildozer',
    'contrib/buildrefactor/src/python/pants/contrib/buildrefactor:meta_rename',
    'contrib/buildrefactor/tests/python/pants_test/contrib/buildrefactor:buildozer_util',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/base:build_environment',
    'tests/python/pants_test/subsystem:subsystem_utils',
    'tests/python/pants_test/tasks:task_test_base',
  ]
)