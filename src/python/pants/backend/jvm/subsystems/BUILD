# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'jvm_tool_mixin',
  sources = ['jvm_tool_mixin.py'],
  dependencies = [
    'src/python/pants/base:exceptions',
    'src/python/pants/option',
    ],
  )

python_library(
  name = 'jar_tool',
  sources = ['jar_tool.py'],
  dependencies = [
    ':jvm_tool_mixin',
    'src/python/pants/base:workunit',
    'src/python/pants/option',
    'src/python/pants/subsystem',
    ],
  )
