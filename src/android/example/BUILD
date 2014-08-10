# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

android_binary(
  name='hello',
  sources=rglobs('src/*.java'),
  manifest='AndroidManifest.xml',
  dependencies = [
    ':resources',
    ':debug',
  ],
)

android_resources(
  name='resources',
  manifest='AndroidManifest.xml',
  resource_dir='res'
)

android_keystore(
  name='debug',
  location='/Users/mateor/false',
  properties_file='/Users/mateor/testy'
)
