# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_test_suite(
  name = 'targets',
  dependencies = [
    pants(':artifact'),
    pants(':bundle'),
    pants(':exclusive'),
    pants(':internal'),
    pants(':jar_library'),
    pants(':pants_target'),
    pants(':python_binary'),
    pants(':python_target'),
    pants(':target'),
    pants(':util'),
  ]
)

python_tests(
  name = 'artifact',
  sources = ['test_artifact.py'],
  dependencies = [
    pants('src/python/pants/base:parse_context'),
    pants('src/python/pants/targets:common'),
    pants('src/python/pants/targets:jvm'),
  ]
)

python_tests(
  name = 'bundle',
  sources = ['test_bundle.py'],
  dependencies = [
    pants('tests/python/pants_test:base-test'),
    pants('src/python/pants/base:parse_context'),
    pants('src/python/pants/targets:jvm'),
  ]
)

python_tests(
  name = 'exclusive',
  sources = ['test_exclusive.py'],
  dependencies = [
    pants('tests/python/pants_test/testutils'),
    pants('src/python/pants/base:config'),
    pants('src/python/pants/goal:context'),
    pants('src/python/pants/tasks:check_exclusives'),
  ]
)

python_tests(
  name = 'internal',
  sources = ['test_internal.py'],
  dependencies = [
    pants('tests/python/pants_test/testutils'),
    pants('src/python/pants/base:parse_context'),
    pants('src/python/pants/base:target'),
    pants('src/python/pants/targets:common'),
  ]
)

python_tests(
  name = 'jar_library',
  sources = ['test_jar_library.py'],
  dependencies = [
    pants('src/python/pants/base:parse_context'),
    pants('src/python/pants/base:target'),
    pants('src/python/pants/targets:jvm'),
  ]
)

python_tests(
  name = 'pants_target',
  sources = ['test_pants_target.py'],
  dependencies = [
    pants('src/python/pants/base:parse_context'),
    pants('src/python/pants/base:target'),
    pants('src/python/pants/targets:common'),
  ]
)

python_tests(
  name = 'python_binary',
  sources = ['test_python_binary.py'],
  dependencies = [
    pants('tests/python/pants_test:base-test'),
    pants('src/python/pants/base:parse_context'),
    pants('src/python/pants/base:target'),
    pants('src/python/pants/targets:python'),
  ]
)

python_tests(
  name = 'target',
  sources = ['test_target.py'],
  dependencies = [
    pants('src/python/pants/base:parse_context'),
    pants('src/python/pants/base:target'),
  ]
)

python_tests(
  name = 'python_target',
  sources = ['test_python_target.py'],
  dependencies = [
    pants('tests/python/pants_test:base-test'),
    pants('src/python/pants/base:parse_context'),
    pants('src/python/pants/base:target'),
    pants('src/python/pants/targets:python'),
  ]
)

python_tests(
  name = 'util',
  sources = ['test_util.py'],
  dependencies = [
    pants('src/python/pants/targets:common'),
  ]
)
