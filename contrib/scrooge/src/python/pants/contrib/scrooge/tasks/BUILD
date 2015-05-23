# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'tasks',
  dependencies = [
    ':scrooge_gen',
    ':thrift_linter',
  ],
)

python_library(
  name = 'scrooge_gen',
  sources = ['scrooge_gen.py'],
  dependencies = [
    ':java_thrift_library_fingerprint_strategy',
    '3rdparty/python/twitter/commons:twitter.common.collections',
    'src/python/pants/backend/codegen/targets:java',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/backend/jvm/targets:scala',
    'src/python/pants/backend/jvm/tasks:jvm_tool_task_mixin',
    'src/python/pants/backend/jvm/tasks:nailgun_task',
    'src/python/pants/base:address',
    'src/python/pants/base:address_lookup_error',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:exceptions',
    'src/python/pants/option',
    'src/python/pants/util:dirutil',
    'src/python/pants:thrift_util',
  ],
)

python_library(
  name = 'thrift_linter',
  sources = ['thrift_linter.py'],
  dependencies = [
    'src/python/pants/backend/jvm/tasks:jvm_tool_task_mixin',
    'src/python/pants/backend/jvm/tasks:nailgun_task',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:workunit',
    'src/python/pants/option',
  ],
)

python_library(
  name = 'java_thrift_library_fingerprint_strategy',
  sources = ['java_thrift_library_fingerprint_strategy.py'],
  dependencies = [
    'src/python/pants/backend/codegen/targets:java',
    'src/python/pants/base:fingerprint_strategy',
  ],
)
