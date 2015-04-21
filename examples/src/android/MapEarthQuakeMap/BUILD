# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

android_binary(
  name='map-quaker',
  sources=rglobs('src/course/examples/maps/earthquakemap/*java'),
  manifest='AndroidManifest.xml',
  dependencies=[
    'examples/src/android/google-play-services_lib:google-play-services_lib',
    ':play-services',
    ':resources',
    ':support-unpacked',
  ],
)

android_resources(
  name='resources',
  manifest='AndroidManifest.xml',
  resource_dir='res'
)

unpacked_jars(name='play-services',
  libraries=['3rdparty/android:google-play-services'],
  include_patterns=[
    'com/google/**/*.class',
  ],
)

unpacked_jars(name='support-unpacked',
  libraries=['3rdparty/android:android-support-v4'],
  include_patterns=[
    'android/**/*.java',
  ],
)