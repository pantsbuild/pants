# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

contrib_plugin(
  name='plugin',
  dependencies=[
    'contrib/android/src/python/pants/contrib/android/targets:android',
    'contrib/android/src/python/pants/contrib/android/tasks:aapt_builder',
    'contrib/android/src/python/pants/contrib/android/tasks:aapt_gen',
    'contrib/android/src/python/pants/contrib/android/tasks:aapt_task',
    'contrib/android/src/python/pants/contrib/android/tasks:android_task',
    'contrib/android/src/python/pants/contrib/android/tasks:dx_compile',
    'contrib/android/src/python/pants/contrib/android/tasks:sign_apk',
    'contrib/android/src/python/pants/contrib/android/tasks:unpack_libraries',
    'contrib/android/src/python/pants/contrib/android/tasks:zipalign',
    'src/python/pants/build_graph',
    'src/python/pants/goal:task_registrar',
  ],
  distribution_name='pantsbuild.pants.contrib.android',
  description='Android Pants plugin',
  additional_classifiers=[
    'Topic :: Software Development :: Code Generators'
  ],
  build_file_aliases=True,
  register_goals=True,
)

python_library(
  name='android_config_util',
  sources =['android_config_util.py'],
  dependencies = [
    'src/python/pants/util:dirutil',
  ],
)

python_library(
  name='android_distribution',
  sources=['distribution/android_distribution.py'],
  dependencies = [
    'src/python/pants/util:dirutil',
  ],
)

python_library(
  name='keystore_resolver',
  sources=['keystore/keystore_resolver.py'],
  dependencies = [
    'src/python/pants/option',
  ],
)

python_library(
  name='android_manifest_parser',
  sources =['android_manifest_parser.py'],
  dependencies = [
    'src/python/pants/util:xml_parser',
  ],
)
