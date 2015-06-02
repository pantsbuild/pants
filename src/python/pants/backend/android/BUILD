# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'plugin',
  sources = ['register.py'],
  dependencies = [
    'src/python/pants/backend/android/targets:android',
    'src/python/pants/backend/android/tasks:all',
    'src/python/pants/base:build_file_aliases',
    'src/python/pants/goal:task_registrar',
  ],
  provides = pants_setup_py(
    name = 'pantsbuild.pants.backend.android',
    description = 'Support for android projects.',
    namespace_packages = ['pants', 'pants.backend'],
  )
)

python_library(
  name = 'android_config_util',
  sources =['android_config_util.py'],
  dependencies = [
    'src/python/pants/util:dirutil',
  ]
)

python_library(
  name = 'android_distribution',
  sources = ['distribution/android_distribution.py'],
  dependencies = [
    'src/python/pants/util:dirutil',
  ]
)

python_library(
  name = 'keystore_resolver',
  sources = ['keystore/keystore_resolver.py'],
  dependencies = [
    'src/python/pants/base:config',
  ]
)

python_library(
  name = 'android_manifest_parser',
  sources =['android_manifest_parser.py'],
  dependencies = [
    'src/python/pants/util:xml_parser',
  ]
)