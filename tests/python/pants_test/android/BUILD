# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

target(
  name = 'android',
  dependencies = [
    ':android_config_util',
    ':android_distribution',
    ':android_manifest_parser',
    ':keystore_resolver',
    'tests/python/pants_test/android/tasks',
  ]
)

target(
  name = 'integration',
  dependencies = [
    'tests/python/pants_test/android/tasks:integration',
  ]
)

python_tests(
  name = 'android_integration_test',
  sources = [
    'android_integration_test.py',
  ],
  dependencies = [
    'src/python/pants/java:distribution',
    'tests/python/pants_test:int-test',
  ],
)

python_library(
  name = 'android_base',
  sources = [
    'test_android_base.py',
  ],
  dependencies = [
    '3rdparty/python/twitter/commons:twitter.common.collections',
    'src/python/pants/backend/android/targets:android',
    'src/python/pants/backend/android/tasks:all',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'tests/python/pants_test/tasks:base'
  ]
)

python_tests(
  name = 'android_config_util',
  sources = [
    'test_android_config_util.py',
  ],
  dependencies = [
    'src/python/pants/backend/android:android_config_util',
    'src/python/pants/util:contextutil',
  ]
)

python_tests(
  name = 'android_manifest_parser',
  sources = [
    'test_android_manifest_parser.py',
  ],
  dependencies = [
    'src/python/pants/backend/android:android_manifest_parser',
    'src/python/pants/util:xml_parser',
  ]
)

python_tests(
  name = 'android_distribution',
  sources = [
    'test_android_distribution.py',
  ],
  dependencies = [
    'src/python/pants/backend/android:android_distribution',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'tests/python/pants_test/android:android_base',
  ]
)

python_tests(
  name = 'keystore_resolver',
  sources = [
    'test_keystore_resolver.py',
  ],
  dependencies = [
    'src/python/pants/backend/android:keystore_resolver',
    'src/python/pants/util:contextutil',
  ]
)
