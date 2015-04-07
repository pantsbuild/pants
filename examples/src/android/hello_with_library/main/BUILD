# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

android_binary(
  name='hello_with_library',
  sources=rglobs('src/*.java'),
  manifest='AndroidManifest.xml',
  dependencies = [
    'examples/src/android/example_library',
    ':resources',
    ':support-unpacked',
  ],
)

android_resources(
  name='resources',
  manifest='AndroidManifest.xml',
  resource_dir='res'
)

unpacked_jars(name='support-unpacked',
  libraries=['3rdparty/android:android-support-v4'],
  include_patterns=[
    'android/**/*.class',
  ],
)