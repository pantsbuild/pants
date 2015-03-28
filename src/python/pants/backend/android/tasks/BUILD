# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'all',
  dependencies = [
    ':android_task',
    ':aapt_builder',
    ':aapt_gen',
    ':aapt_task',
    ':dx_compile',
    ':sign_apk',
    ':zipalign',
  ],
)

python_library(
  name = 'android_task',
  sources = ['android_task.py'],
  dependencies = [
    'src/python/pants/backend/core/tasks:common',
    'src/python/pants/backend/android:android_distribution',
  ],
)

python_library(
  name = 'aapt_builder',
  sources = ['aapt_builder.py'],
  dependencies = [
    'src/python/pants/backend/android/targets:android',
    'src/python/pants/backend/android/tasks:aapt_task',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:workunit',
    'src/python/pants/util:dirutil',
  ],
)

python_library(
  name = 'aapt_gen',
  sources = ['aapt_gen.py'],
  dependencies = [
    '3rdparty/python/twitter/commons:twitter.common.collections',
    'src/python/pants/backend/android/targets:android',
    'src/python/pants/backend/android/tasks:aapt_task',
    'src/python/pants/backend/codegen/tasks:code_gen',
    'src/python/pants/backend/core/tasks:common',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/base:address',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:workunit',
    'src/python/pants/util:dirutil',
  ],
)

python_library(
  name = 'aapt_task',
  sources = ['aapt_task.py'],
  dependencies = [
    'src/python/pants/backend/android/tasks:android_task',
  ],
)

python_library(
  name = 'dx_compile',
  sources = ['dx_compile.py'],
  dependencies = [
    'src/python/pants/backend/android/targets:android',
    'src/python/pants/backend/android/tasks:android_task',
    'src/python/pants/backend/core/tasks:common',
    'src/python/pants/backend/jvm/tasks:nailgun_task',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:workunit',
    'src/python/pants/util:dirutil',
  ],
)

python_library(
  name = 'sign_apk',
  sources = ['sign_apk.py'],
  dependencies = [
    'src/python/pants/backend/android:android_config_util',
    'src/python/pants/backend/android:keystore_resolver',
    'src/python/pants/backend/android/targets:android',
    'src/python/pants/backend/core/tasks:common',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:workunit',
    'src/python/pants/java/distribution:distribution',
    'src/python/pants/util:dirutil',
  ],
)

python_library(
  name = 'zipalign',
  sources = ['zipalign.py'],
  dependencies = [
    'src/python/pants/backend/android/targets:android',
    'src/python/pants/backend/android/tasks:android_task',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:workunit',
    'src/python/pants/util:dirutil',
  ],
)
