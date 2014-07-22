# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_test_suite(
  name = 'java',
  dependencies = [
    pants(':executor'),
    pants('tests/python/pants_test/java/distribution'),
  ]
)

python_tests(
  name = 'executor',
  sources = ['test_executor.py'],
  dependencies = [
    pants('3rdparty/python/twitter/commons:twitter.common.contextutil'),
    pants('src/python/pants/java:distribution'),
    pants('src/python/pants/java:executor'),
    pants('src/python/pants/util:dirutil'),
  ]
)
