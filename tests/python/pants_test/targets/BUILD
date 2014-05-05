# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_test_suite(
  name = 'targets',
  dependencies = [
    pants(':artifact'),
    pants(':bundle'),
    pants(':exclusive'),
    pants(':sort_targets'),
    pants(':jar_library'),
    pants(':java_thrift_library'),
    pants(':python_binary'),
    pants(':python_target'),
    pants(':scala_library'),
  ]
)

python_tests(
  name = 'artifact',
  sources = ['test_artifact.py'],
  dependencies = [
    pants('tests/python/pants_test/testutils'),
    pants('src/python/pants/targets:common'),
    pants('src/python/pants/targets:jvm'),
  ]
)

python_tests(
  name = 'bundle',
  sources = ['test_bundle.py'],
  dependencies = [
    pants('tests/python/pants_test:base-test'),
    pants('src/python/pants/targets:jvm'),
  ]
)

python_tests(
  name = 'exclusive',
  sources = ['test_exclusive.py'],
  dependencies = [
    pants('3rdparty/python/twitter/commons:twitter.common.dirutil'),
    pants('tests/python/pants_test/testutils'),
    pants('tests/python/pants_test:base-test'),
    pants('src/python/pants/base:config'),
    pants('src/python/pants/goal:goal'),
    pants('src/python/pants/tasks:check_exclusives'),
  ]
)

python_tests(
  name = 'sort_targets',
  sources = ['test_sort_targets.py'],
  dependencies = [
    pants('tests/python/pants_test/testutils'),
    pants('src/python/pants/base:target'),
    pants('src/python/pants/base:build_graph'),
    pants('src/python/pants/base:payload'),
    pants('src/python/pants/targets:common'),
  ]
)

python_tests(
  name = 'jar_library',
  sources = ['test_jar_library.py'],
  dependencies = [
    pants('src/python/pants/base:target'),
    pants('src/python/pants/targets:jvm'),
  ]
)

python_tests(
  name = 'java_thrift_library',
  sources = ['test_java_thrift_library.py'],
  dependencies = [
    pants('src/python/pants/targets:java'),
    pants('tests/python/pants_test:base-test'),
    pants('tests/python/pants_test/base:base-test'),
  ]
)

python_tests(
  name = 'python_binary',
  sources = ['test_python_binary.py'],
  dependencies = [
    pants('tests/python/pants_test:base-test'),
    pants('src/python/pants/base:target'),
    pants('src/python/pants/targets:python'),
  ]
)

python_tests(
  name = 'scala_library',
  sources = ['test_scala_library.py'],
  dependencies = [
    pants('src/python/pants/targets:java'),
    pants('src/python/pants/targets:scala'),
    pants('tests/python/pants_test:base-test'),
  ]
)

python_tests(
  name = 'python_target',
  sources = ['test_python_target.py'],
  dependencies = [
    pants('tests/python/pants_test:base-test'),
    pants('src/python/pants/base:target'),
    pants('src/python/pants/targets:python'),
  ]
)

