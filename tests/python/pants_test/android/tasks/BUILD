# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name = 'aapt_builder',
  sources = [
    'test_aapt_builder.py',
  ],
  dependencies = [
    'src/python/pants/backend/android/tasks:aapt_builder',
    'tests/python/pants_test/android:android_base',
  ],
)

python_tests(
  name = 'aapt_builder_integration',
  sources = [
    'test_aapt_builder_integration.py',
  ],
  dependencies = [
    'src/python/pants/util:contextutil',
    'tests/python/pants_test/android:android_integration_test',
  ],
  tags = {'integration'},
)

python_tests(
  name = 'aapt_gen',
  sources = [
    'test_aapt_gen.py',
  ],
  dependencies = [
    'src/python/pants/backend/android/tasks:all',
    'tests/python/pants_test/android:android_base',
  ],
)

python_tests(
  name = 'aapt_gen_integration',
  sources = [
    'test_aapt_gen_integration.py',
  ],
  dependencies = [
    'src/python/pants/util:contextutil',
    'tests/python/pants_test/android:android_integration_test',
  ],
  tags = {'integration'},
)

python_tests(
  name = 'aapt_task',
  sources = [
    'test_aapt_task.py',
  ],
  dependencies = [
    'src/python/pants/backend/android/tasks:all',
    'tests/python/pants_test/android:android_base',
  ],
)

python_tests(
  name = 'dx_compile',
  sources = [
    'test_dx_compile.py',
  ],
  dependencies = [
    'src/python/pants/backend/android/tasks:all',
    'src/python/pants/backend/jvm/tasks:classpath_util',
    'src/python/pants/base:build_environment',
    'src/python/pants/goal:products',
    'src/python/pants/util:dirutil',
    'tests/python/pants_test/android:android_base',
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
  tags = {'integration'},
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
  tags = {'integration'},
)

python_tests(
  name = 'unpack_libraries',
  sources = [
    'test_unpack_libraries.py',
  ],
  dependencies = [
    'src/python/pants/backend/android/targets:android',
    'src/python/pants/backend/android/tasks:unpack_libraries',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/backend/jvm/tasks:jar_import_products',
    'src/python/pants/backend/jvm:jar_dependency_utils',
    'src/python/pants/fs:fs',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'tests/python/pants_test/android:android_base',
  ],
)

python_tests(
  name = 'unpack_libraries_integration',
  sources = [
    'test_unpack_libraries_integration.py',
  ],
  dependencies = [
    'tests/python/pants_test/android:android_integration_test',
  ],
  tags = {'integration'},
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
  tags = {'integration'},
)
