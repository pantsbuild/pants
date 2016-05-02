# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name = 'aapt_builder',
  sources = [
    'test_aapt_builder.py',
  ],
  dependencies = [
    'contrib/android/src/python/pants/contrib/android/tasks:aapt_builder',
    'contrib/android/tests/python/pants_test/contrib/android:android_base',
  ],
)

python_tests(
  name = 'aapt_builder_integration',
  sources = [
    'test_aapt_builder_integration.py',
  ],
  dependencies = [
    'contrib/android/tests/python/pants_test/contrib/android:android_integration_test',
  ],
  tags = {'integration'},
)

python_tests(
  name = 'aapt_gen',
  sources = [
    'test_aapt_gen.py',
  ],
  dependencies = [
    'contrib/android/src/python/pants/contrib/android/tasks:aapt_gen',
    'contrib/android/tests/python/pants_test/contrib/android:android_base',
  ],
)

python_tests(
  name = 'aapt_gen_integration',
  sources = [
    'test_aapt_gen_integration.py',
  ],
  dependencies = [
    'contrib/android/tests/python/pants_test/contrib/android:android_integration_test',
  ],
  tags = {'integration'},
)

python_tests(
  name = 'aapt_task',
  sources = [
    'test_aapt_task.py',
  ],
  dependencies = [
    'contrib/android/src/python/pants/contrib/android/tasks:aapt_gen',
    'contrib/android/tests/python/pants_test/contrib/android:android_base',
  ],
)

python_tests(
  name = 'dx_compile',
  sources = [
    'test_dx_compile.py',
  ],
  dependencies = [
    'contrib/android/src/python/pants/contrib/android/tasks:dx_compile',
    'contrib/android/tests/python/pants_test/contrib/android:android_base',
    'src/python/pants/backend/jvm/tasks:classpath_util',
    'src/python/pants/base:build_environment',
    'src/python/pants/util:dirutil',
  ],
)

python_tests(
  name = 'dx_compile_integration',
  sources = [
    'test_dx_compile_integration.py',
  ],
  dependencies = [
    'contrib/android/tests/python/pants_test/contrib/android:android_integration_test',
  ],
  tags = {'integration'},
)

python_tests(
  name = 'sign_apk',
  sources = [
    'test_sign_apk.py',
  ],
  dependencies = [
    'contrib/android/src/python/pants/contrib/android/tasks:sign_apk',
    'contrib/android/tests/python/pants_test/contrib/android:android_base',
    'src/python/pants/base:exceptions',
    'src/python/pants/util:contextutil',
  ],
)

python_tests(
  name = 'sign_apk_integration',
  sources = [
    'test_sign_apk_integration.py',
  ],
  dependencies = [
    'contrib/android/tests/python/pants_test/contrib/android:android_integration_test',
  ],
  tags = {'integration'},
)

python_tests(
  name = 'unpack_libraries',
  sources = [
    'test_unpack_libraries.py',
  ],
  dependencies = [
    'contrib/android/src/python/pants/contrib/android/targets:android',
    'contrib/android/src/python/pants/contrib/android/tasks:unpack_libraries',
    'contrib/android/tests/python/pants_test/contrib/android:android_base',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/backend/jvm/tasks:jar_import_products',
    'src/python/pants/backend/jvm:jar_dependency_utils',
    'src/python/pants/fs',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
  ],
)

python_tests(
  name = 'unpack_libraries_integration',
  sources = [
    'test_unpack_libraries_integration.py',
  ],
  dependencies = [
    'contrib/android/tests/python/pants_test/contrib/android:android_integration_test',
  ],
  tags = {'integration'},
)

python_tests(
  name = 'zipalign',
  sources = [
    'test_zipalign.py',
  ],
  dependencies = [
    'contrib/android/src/python/pants/contrib/android/tasks:zipalign',
    'contrib/android/tests/python/pants_test/contrib/android:android_base',
  ],
)

python_tests(
  name = 'zipalign_integration',
  sources = [
    'test_zipalign_integration.py',
  ],
  dependencies = [
    'contrib/android/tests/python/pants_test/contrib/android:android_integration_test',
  ],
  tags = {'integration'},
)
