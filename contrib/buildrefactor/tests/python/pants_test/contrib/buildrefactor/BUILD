# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


python_library(
  name='buildozer_util',
  sources=['buildozer_util.py'],
  tags = {"partially_type_checked"},
)


python_tests(
  name='buildozer',
  sources=['test_buildozer.py'],
  dependencies=[
    ':buildozer_util',
    'contrib/buildrefactor/src/python/pants/contrib/buildrefactor',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/util:contextutil',
    'src/python/pants/testutil/subsystem',
    'src/python/pants/testutil:task_test_base',
  ],
  tags = {'partially_type_checked'},
)


python_tests(
  name='meta_rename',
  sources=['test_meta_rename.py'],
  dependencies=[
    ':buildozer_util',
    'contrib/buildrefactor/src/python/pants/contrib/buildrefactor',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/base:build_environment',
    'src/python/pants/testutil/subsystem',
    'src/python/pants/testutil:task_test_base',
  ],
  tags = {'partially_type_checked'},
)


python_tests(
  name='meta_rename_integration',
  sources=['test_meta_rename_integration.py'],
  dependencies=[
    'src/python/pants/testutil:int-test',
    'testprojects/tests/java/org/pantsbuild/testproject:buildrefactor_directory',
  ],
  tags={'integration', 'partially_type_checked'},
)


python_tests(
  name='buildozer_integration',
  sources=['test_buildozer_integration.py'],
  dependencies=[
    'src/python/pants/testutil:int-test',
    'testprojects/tests/java/org/pantsbuild/testproject:buildrefactor_directory',
  ],
  tags={'integration', 'partially_type_checked'},
)
