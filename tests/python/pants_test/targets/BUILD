# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'base',
  dependencies = [
    'tests/python/pants_test:base_test',
  ],
)

target(
  name = 'targets',
  dependencies = [
    ':java_agent',
    ':python_binary',
    ':python_target',
    ':scala_library',
    ':sort_targets',
    ':wiki_page'
  ]
)

target(
  name = 'integration',
  dependencies = [
    ':scala_library_integration',
    ':unknown_arguments_integration',
  ],
)

python_tests(
  name = 'unknown_arguments_integration',
  sources = ['test_unknown_arguments_integration.py'],
  dependencies = [
    'src/python/pants/util:contextutil',
    'tests/python/pants_test:int-test',
  ]
)

python_tests(
  name = 'sort_targets',
  sources = ['test_sort_targets.py'],
  dependencies = [
    ':base',
    'src/python/pants/base:build_graph',
    'src/python/pants/backend/core/targets:common',
  ]
)

python_tests(
  name = 'java_agent',
  sources = ['test_java_agent.py'],
  dependencies=[
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/base:build_file_aliases',
    'src/python/pants/base:exceptions',
    'tests/python/pants_test:base_test',
  ]
)

python_tests(
  name = 'jvm_app_integration',
  sources = ['test_jvm_app_integration.py'],
  dependencies = [
    'tests/python/pants_test:int-test',
  ]
)

python_tests(
  name = 'python_binary',
  sources = ['test_python_binary.py'],
  dependencies = [
    ':base',
    'src/python/pants/base:target',
    'src/python/pants/backend/python/targets:python',
  ]
)

python_tests(
  name = 'scala_library',
  sources = ['test_scala_library.py'],
  dependencies = [
    ':base',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/backend/jvm/targets:scala',
    'src/python/pants/base:build_file_aliases',
  ]
)

python_tests(
  name = 'scala_library_integration',
  sources = ['test_scala_library_integration.py'],
  dependencies = [
    'tests/python/pants_test:int-test',
  ]
)

python_tests(
  name = 'python_target',
  sources = ['test_python_target.py'],
  dependencies = [
    'src/python/pants/backend/core/targets:common',
    'src/python/pants/backend/jvm:artifact',
    'src/python/pants/backend/jvm:repository',
    'src/python/pants/backend/python/targets:python',
    'src/python/pants/backend/python:python_artifact',
    'src/python/pants/base:exceptions',
    'tests/python/pants_test:base_test'
  ]
)

python_tests(
  name = 'wiki_page',
  sources = ['test_wiki_page.py'],
  dependencies = [
    '3rdparty/python/twitter/commons:twitter.common.confluence',
    'src/python/pants/backend/core/targets:common',
    'tests/python/pants_test:base_test',
  ]
)
