# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'android_integration_test',
  sources = [
    'android_integration_test.py',
  ],
  dependencies = [
    'src/python/pants/java/distribution',
    'tests/python/pants_test/subsystem:subsystem_utils',
    'tests/python/pants_test:int-test',
  ],
)

python_library(
  name = 'android_base',
  sources = [
    'test_android_base.py',
  ],
  dependencies = [
    '3rdparty/python:twitter.common.collections',
    'contrib/android/src/python/pants/contrib/android/targets:android',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'tests/python/pants_test/jvm:jvm_tool_task_test_base',
  ],
)

python_tests(
  name = 'android_config_util',
  sources = [
    'test_android_config_util.py',
  ],
  dependencies = [
    'contrib/android/src/python/pants/contrib/android:android_config_util',
    'src/python/pants/util:contextutil',
  ],
)

python_tests(
  name = 'android_manifest_parser',
  sources = [
    'test_android_manifest_parser.py',
  ],
  dependencies = [
    'contrib/android/src/python/pants/contrib/android:android_manifest_parser',
    'tests/python/pants_test/util:xml_test_base',
  ],
)

python_tests(
  name = 'android_distribution',
  sources = [
    'test_android_distribution.py',
  ],
  dependencies = [
    ':android_base',
    'contrib/android/src/python/pants/contrib/android:android_distribution',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'tests/python/pants_test:base_test',
  ],
)

python_tests(
  name = 'keystore_resolver',
  sources = [
    'test_keystore_resolver.py',
  ],
  dependencies = [
    'contrib/android/src/python/pants/contrib/android:keystore_resolver',
    'src/python/pants/util:contextutil',
  ],
)
