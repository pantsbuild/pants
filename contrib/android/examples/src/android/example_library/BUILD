# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

android_library(
  name='example_library',
  manifest='AndroidManifest.xml',
  libraries=['contrib/android/examples/3rdparty/android:android-support-v4'],
  include_patterns=[
    'android/**/*.class',
  ],
  dependencies=[
    ':gms-library',
    ':resources',
  ],
)

android_resources(
  name='resources',
  manifest='AndroidManifest.xml',
  resource_dir='res'
)

android_library(
  name='gms-library',
  libraries=['contrib/android/examples/3rdparty/android:google-play-services'],
  include_patterns=[
    '**/*.class',
  ],
  dependencies = [
  ]
)
