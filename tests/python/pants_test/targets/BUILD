# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'base',
  dependencies = [
    pants('tests/python/pants_test:base_test'),
  ],
)

python_test_suite(
  name = 'targets',
  dependencies = [
    pants(':artifact'),
    pants(':exclusive'),
    pants(':jar_library'),
    pants(':java_tests'),
    pants(':java_thrift_library'),
    pants(':jvm_app'),
    pants(':python_binary'),
    pants(':python_target'),
    pants(':scala_library'),
    pants(':sort_targets'),
    pants(':wiki_page')
  ]
)

python_test_suite(
  name = 'integration',
  dependencies = [
    pants(':scala_library_integration'),
  ],
)

python_tests(
  name = 'artifact',
  sources = ['test_artifact.py'],
  dependencies = [
    pants(':base'),
    pants('src/python/pants/backend/core/targets:common'),
    pants('src/python/pants/backend/jvm/targets:jvm'),
  ]
)

python_tests(
  name = 'jvm_app',
  sources = ['test_jvm_app.py'],
  dependencies = [
    pants(':base'),
    pants('src/python/pants/backend/core:plugin'),
    pants('src/python/pants/backend/jvm:plugin'),
    pants('src/python/pants/base:exceptions'),
  ]
)

python_tests(
  name = 'exclusive',
  sources = ['test_exclusive.py'],
  dependencies = [
    pants(':base'),
    pants('src/python/pants/base:config'),
    pants('src/python/pants/goal:goal'),
    pants('src/python/pants/backend/core/tasks:check_exclusives'),
    pants('src/python/pants/util:contextutil'),
  ]
)

python_tests(
  name = 'sort_targets',
  sources = ['test_sort_targets.py'],
  dependencies = [
    pants(':base'),
    pants('src/python/pants/base:target'),
    pants('src/python/pants/base:build_graph'),
    pants('src/python/pants/base:payload'),
    pants('src/python/pants/backend/core/targets:common'),
  ]
)

python_tests(
  name = 'jar_library',
  sources = ['test_jar_library.py'],
  dependencies = [
    pants(':base'),
    pants('src/python/pants/base:target'),
    pants('src/python/pants/backend/jvm/targets:jvm'),
  ]
)

python_tests(
  name = 'java_thrift_library',
  sources = ['test_java_thrift_library.py'],
  dependencies = [
    pants(':base'),
    pants('src/python/pants/backend/codegen/targets:java'),
    pants('src/python/pants/backend/jvm/targets:java'),
    pants('src/python/pants/base:build_file_aliases'),
    pants('tests/python/pants_test/base:context_utils'),
  ]
)

python_tests(
  name = 'java_tests',
  sources = ['test_java_tests.py'],
  dependencies = [
    pants(':base'),
    pants('src/python/pants/backend/core'),
    pants('src/python/pants/backend/jvm/targets:java'),
    pants('tests/python/pants_test/base:context_utils'),
  ]
)

python_tests(
  name = 'python_binary',
  sources = ['test_python_binary.py'],
  dependencies = [
    pants(':base'),
    pants('src/python/pants/base:target'),
    pants('src/python/pants/backend/python/targets:python'),
  ]
)

python_tests(
  name = 'scala_library',
  sources = ['test_scala_library.py'],
  dependencies = [
    pants(':base'),
    pants('src/python/pants/backend/jvm/targets:java'),
    pants('src/python/pants/backend/jvm/targets:jvm'),
    pants('src/python/pants/backend/jvm/targets:scala'),
    pants('src/python/pants/base:build_file_aliases'),
  ]
)

python_tests(
  name = 'scala_library_integration',
  sources = ['test_scala_library_integration.py'],
  dependencies = [
    pants('tests/python/pants_test:int-test'),
  ]
)


python_tests(
  name = 'python_target',
  sources = ['test_python_target.py'],
  dependencies = [
    pants(':base'),
    pants('src/python/pants/backend/jvm/targets:jvm'),
    pants('src/python/pants/backend/python/targets:python'),
    pants('src/python/pants/backend/python:python_artifact'),
    pants('src/python/pants/base:exceptions'),
    pants('src/python/pants/base:source_root'),
    pants('src/python/pants/base:target'),
  ]
)

python_tests(
  name = 'wiki_page',
  sources = ['test_wiki_page.py'],
  dependencies = [
    pants('3rdparty/python/twitter/commons:twitter.common.confluence'),
    pants('src/python/pants/backend/core/targets:common'),
    pants('tests/python/pants_test:base_test'),
  ]
)
