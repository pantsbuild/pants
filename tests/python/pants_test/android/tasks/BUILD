# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


python_test_suite(
  name = 'tasks',
  dependencies = [
    pants(':aapt_gen'),
  ],
)

python_test_suite(
  name = 'integration',
  dependencies = [],
)

python_tests(
  name = 'aapt_gen',
  sources = ['test_aapt_gen.py'],
  dependencies = [
    pants('src/python/pants/backend/android/targets:android'),
    pants('src/python/pants/backend/android/tasks:all'),
    pants('src/python/pants/base:build_file_aliases'),
    pants('src/python/pants/base:exceptions'),
    pants('tests/python/pants_test/tasks:base'),
    ],
)

python_tests(
  name = 'aapt_gen2',
  sources = ['test_aapt_gen2.py'],
  dependencies = [
    pants('src/python/pants/backend/android/targets:android'),
    pants('src/python/pants/backend/android/tasks:all'),
    pants('src/python/pants/base:build_file_aliases'),
    pants('src/python/pants/base:exceptions'),
    pants('tests/python/pants_test/tasks:base'),
  ],
)


