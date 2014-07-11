# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

android_binary(
  name='hello',
  sources='HelloWorld.java',
  manifest=pants('src/android/example/AndroidManifest.xml'),
  dependencies = [
    pants('src/android/example/res:hello'),
  ],
  resources=[
    pants('src/android/example/res')
  ],
)