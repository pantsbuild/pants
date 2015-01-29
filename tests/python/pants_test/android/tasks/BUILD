# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_test_suite(
  name='tasks',
  dependencies=[
    ':aapt_gen',
  ],
)

python_test_suite(
  name = 'integration',
  dependencies = [
    ':aapt_builder_integration',
    ':dx_compile_integration',
    ':sign_apk_integration',
  ],
)

python_tests(
  name = 'aapt_builder_integration',
  sources = [
    'test_aapt_builder_integration.py',
  ],
  dependencies = [
    'tests/python/pants_test/android:android_integration_test',
  ],
)

python_tests(
  name = 'aapt_gen',
  sources = [
    'test_aapt_gen.py',
  ],
  dependencies = [
    'src/python/pants/backend/android/tasks:all',
  ],
)

python_tests(
  name = 'dx_compile_integration',
  sources = [
    'test_dx_compile_integration.py',
  ],
  dependencies = [
    'tests/python/pants_test/android:android_integration_test',
  ],
)

python_tests(
  name = 'sign_apk',
  sources = [
    'test_sign_apk.py',
  ],
  dependencies = [
    'src/python/pants/backend/android/targets:android',
    'src/python/pants/backend/android/tasks:sign_apk',
    'src/python/pants/base:build_file_aliases',
    'src/python/pants/base:exceptions',
    'src/python/pants/util:contextutil',
    'tests/python/pants_test/tasks:base'
  ],
)

python_tests(
  name = 'sign_apk_integration',
  sources = [
    'test_sign_apk_integration.py',
  ],
  dependencies = [
    'tests/python/pants_test/android:android_integration_test',
  ],
)
