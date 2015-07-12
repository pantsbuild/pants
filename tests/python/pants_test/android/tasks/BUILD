# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

target(
  name='tasks',
  dependencies=[
    ':aapt_gen',
    ':sign_apk',
    ':unpack_libraries',
    ':zipalign',
  ],
)

target(
  name = 'integration',
  dependencies = [
    ':aapt_builder_integration',
    ':dx_compile_integration',
    ':sign_apk_integration',
    ':zipalign_integration',
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
    'src/python/pants/backend/android/tasks:sign_apk',
    'src/python/pants/base:exceptions',
    'src/python/pants/util:contextutil',
    'tests/python/pants_test/android:android_base'
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

python_tests(
  name = 'unpack_libraries',
  sources = [
    'test_unpack_libraries.py',
  ],
  dependencies = [
    'src/python/pants/backend/android/targets:android',
    'src/python/pants/backend/android/tasks:unpack_libraries',
    'src/python/pants/backend/core/targets:common',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/backend/jvm/tasks:ivy_task_mixin',
    'src/python/pants/base:build_file_aliases',
    'src/python/pants/fs:fs',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'tests/python/pants_test/android:android_base',
  ],
)

python_tests(
  name = 'zipalign',
  sources = [
    'test_zipalign.py',
  ],
  dependencies = [
    'src/python/pants/backend/android/tasks:zipalign',
    'src/python/pants/util:contextutil',
    'tests/python/pants_test/android:android_base',
  ],
)

python_tests(
  name = 'zipalign_integration',
  sources = [
    'test_zipalign_integration.py',
  ],
  dependencies = [
    'tests/python/pants_test/android:android_integration_test',
  ],
)
