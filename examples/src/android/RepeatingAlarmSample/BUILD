# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

android_binary(
  name='alarm',
  sources=rglobs('src/main/java/**/*java'),
  manifest='src/main/AndroidManifest.xml',
  dependencies = [
    '3rdparty/android:android-support-v4',
    ':resources',
    ':support-unpacked',
  ],
)

android_resources(
  name='resources',
  manifest='src/main/AndroidManifest.xml',
  resource_dir='src/main/res'
)

unpacked_jars(name='support-unpacked',
  libraries=['3rdparty/android:android-support-v4'],
  include_patterns=[
    'android/support/**/*.class',
  ],
)
