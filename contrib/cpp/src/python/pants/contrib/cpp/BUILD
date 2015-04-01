# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name='plugin',
  sources=['register.py'],
  dependencies=[
    'contrib/cpp/src/python/pants/contrib/cpp/targets:targets',
    'contrib/cpp/src/python/pants/contrib/cpp/tasks:tasks',
    'contrib/cpp/src/python/pants/contrib/cpp/toolchain:toolchain',
    'src/python/pants/base:build_file_aliases',
    'src/python/pants/goal:task_registrar',
  ],
  provides=contrib_setup_py(
    name='pantsbuild.pants.contrib.cpp',
    description='C++ pants plugin.',
  ),
)
