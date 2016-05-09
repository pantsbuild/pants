# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'android',
  sources = [
    'android_binary.py',
    'android_dependency.py',
    'android_library.py',
    'android_resources.py',
    'android_target.py',
  ],
  dependencies = [
    'contrib/android/src/python/pants/contrib/android:android_manifest_parser',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:payload',
    'src/python/pants/base:payload_field',
    'src/python/pants/util:memo',
  ],
)
