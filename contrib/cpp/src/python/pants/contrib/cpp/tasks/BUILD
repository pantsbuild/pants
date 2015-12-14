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
  dependencies=[
    'contrib/cpp/src/python/pants/contrib/cpp/toolchain:toolchain',
    'contrib/cpp/src/python/pants/contrib/cpp/targets:targets',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:workunit',
    'src/python/pants/task',
    'src/python/pants/util:dirutil',
  ],
)
