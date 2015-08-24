# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'jvm_tool_mixin',
  sources = ['jvm_tool_mixin.py'],
  dependencies = [
    'src/python/pants/base:address_lookup_error',
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

python_library(
  name = 'jvm',
  sources = ['jvm.py'],
  dependencies = [
    'src/python/pants/option',
    'src/python/pants/subsystem',
    'src/python/pants/util:strutil',
    'src/python/pants/util:osutil',
  ],
)

python_library(
  name = 'jvm_platform',
  sources = ['jvm_platform.py'],
  dependencies = [
    'src/python/pants/base:revision',
    'src/python/pants/option',
    'src/python/pants/subsystem',
    'src/python/pants/util:memo',
    'src/python/pants/java/distribution',
  ],
)

python_library(
  name = 'scala_platform',
  sources = ['scala_platform.py'],
  dependencies = [
    ':jvm_tool_mixin',
    'src/python/pants/option',
    'src/python/pants/subsystem',
  ],
)