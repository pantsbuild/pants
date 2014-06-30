# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'all',
  dependencies = [
    ':android',
  ],
)

python_library(
  name = 'android',
  sources = [
    'android_binary.py',
    'android_target.py',
    'android_resources.py',
  ],
  dependencies = [
    pants('src/python/pants/base:build_manual'),
    pants('src/python/pants/base:payload'),
    pants('src/python/pants/base:target'),
    pants('src/python/pants/backend/core/targets:common'),
  ],
)