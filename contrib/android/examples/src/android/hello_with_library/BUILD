# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

android_binary(
  name='hello_with_library',
  sources=rglobs('main/src/*.java'),
  manifest='main/AndroidManifest.xml',
  dependencies = [
    ':resources',
    'contrib/android/examples/src/android/example_library',
    ':support-library',
  ],
)

android_resources(
  name='resources',
  manifest='AndroidManifest.xml',
  resource_dir='main/res'
)

android_library(
  name='support-library',
  libraries=['contrib/android/examples/3rdparty/android:android-support-v4'],
  include_patterns=[
    '**/*.class',
  ],
  dependencies = [
  ]
)
