# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

target(
  name='android',
  dependencies=[
    ':android_distribution',
    'tests/python/pants_test/android/tasks',
  ]
)

target(
  name='integration',
  dependencies=[
    'tests/python/pants_test/android/tasks:integration',
  ]
)

python_tests(
  name='android_integration_test',
  sources=[
    'android_integration_test.py',
  ],
  dependencies=[
    'tests/python/pants_test:int-test',
  ],
  coverage=[
    'pants.backend.android',
  ]
)

python_tests(
  name='android_distribution',
  sources=[
    'test_android_distribution.py',
  ],
  dependencies=[
    '3rdparty/python/twitter/commons:twitter.common.collections',
    'src/python/pants/backend/android:android_distribution',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
  ],
  coverage=[
    'pants.backend.android.distribution.android_distribution',
  ]
)
