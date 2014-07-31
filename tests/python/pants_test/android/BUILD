# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_test_suite(
  name = 'android',
  dependencies = [
    ':android_distribution',
  ]
)

python_tests(
  name = 'android_distribution',
  sources = [
    'test_android_distribution.py',
  ],
  dependencies = [
    '3rdparty/python/twitter/commons:twitter.common.collections',
    'src/python/pants/backend/android:android_distribution',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
  ]
)
