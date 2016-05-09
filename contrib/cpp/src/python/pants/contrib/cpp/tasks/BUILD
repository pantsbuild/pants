# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name='tasks',
  sources=[
    'cpp_compile.py',
    'cpp_binary_create.py',
    'cpp_library_create.py',
    'cpp_run.py',
    'cpp_task.py',
  ],
  dependencies = [
    'contrib/cpp/src/python/pants/contrib/cpp/targets',
    'contrib/cpp/src/python/pants/contrib/cpp/toolchain',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:workunit',
    'src/python/pants/task',
    'src/python/pants/util:dirutil',
  ],
)
