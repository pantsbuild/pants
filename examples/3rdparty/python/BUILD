# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# see/edit requirements.txt in this directory to change deps.
python_requirements()

remote_sources(
  name='tensorflow-framework',
  dest=packaged_native_library,
  sources_target=':tensorflow-native-libs',
  args=dict(
    include_relpath='include',
    lib_relpath='',
    native_lib_names = {
      'darwin': ['tensorflow_framework'],
      # On Linux, the shared lib is literally named `libtensorflow_framework.so.1` in tensorflow
      # 1.14. Adding a linker command line argument `-l:lib_tensorflow_framework.so.1` will tell the
      # linker to search for and use a library literally named that filename, without any further
      # trickery.
      'linux': [':libtensorflow_framework.so.1'],
    },
  ),
)

unpacked_whls(
  name='tensorflow-native-libs',
  libraries=[':tensorflow'],
  module_name='tensorflow',
  include_patterns=[
    'include/**/*',
    './*.so*',
    './*.dylib*',
  ],
  within_data_subdir=True,
)

files(
  name='examples_python_3rdparty',
  sources=['**/*'],
)
