# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

android_library(
  name='example_library',
  manifest='AndroidManifest.xml',
  dependencies=[
    '3rdparty/android:android-support-v4',
    ':resources',
  ],
)

android_resources(
  name='resources',
  manifest='AndroidManifest.xml',
  resource_dir='res'
)
