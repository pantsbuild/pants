# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name='tasks',
)

python_library(
  name='scrooge_gen',
  sources=['scrooge_gen.py'],
  dependencies = [
    '3rdparty/python:twitter.common.collections',
    ':thrift_util',
    'src/python/pants/backend/codegen/subsystems:thrift_defaults',
    'src/python/pants/backend/codegen/targets:java',
    'src/python/pants/backend/codegen/tasks:simple_codegen_task',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/backend/jvm/targets:scala',
    'src/python/pants/backend/jvm/tasks:nailgun_task',
    'src/python/pants/base:exceptions',
    'src/python/pants/build_graph',
    'src/python/pants/util:dirutil',
    'src/python/pants/util:memo',
  ],
)

python_library(
  name='thrift_linter',
  sources=['thrift_linter.py'],
  dependencies = [
    ':thrift_util',
    'src/python/pants/backend/jvm/tasks:nailgun_task',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:workunit',
    'src/python/pants/option',
  ],
)

python_library(
  name='thrift_util',
  sources=['thrift_util.py'],
)

python_library(
  name='java_thrift_library_fingerprint_strategy',
  sources=['java_thrift_library_fingerprint_strategy.py'],
  dependencies = [
    'src/python/pants/backend/codegen/targets:java',
    'src/python/pants/base:fingerprint_strategy',
  ],
)
