# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'all',
  dependencies = [
    ':dependencies',
    ':depmap',
    ':eclipse_gen',
    ':ensime_gen',
    ':export',
    ':filedeps',
    ':ide_gen',
    ':idea_gen',
  ],
)

python_library(
  name = 'dependencies',
  sources = ['dependencies.py'],
  dependencies = [
    '3rdparty/python/twitter/commons:twitter.common.collections',
    'src/python/pants/backend/core/tasks:console_task',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:payload_field',
  ],
)

python_library(
  name = 'depmap',
  sources = ['depmap.py'],
  dependencies = [
    '3rdparty/python/twitter/commons:twitter.common.collections',
    'src/python/pants/backend/core/targets:all',
    'src/python/pants/backend/core/tasks:console_task',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/backend/jvm/targets:scala',
    'src/python/pants/backend/jvm:ivy_utils',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:deprecated',
    'src/python/pants/base:exceptions',
  ],
)

python_library(
  name = 'eclipse_gen',
  sources = ['eclipse_gen.py'],
  resources = globs('templates/eclipse/*.mustache', 'templates/eclipse/*.prefs'),
  dependencies = [
    ':ide_gen',
    '3rdparty/python/twitter/commons:twitter.common.collections',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:generator',
    'src/python/pants/util:dirutil',
  ],
)

python_library(
  name = 'ensime_gen',
  sources = ['ensime_gen.py'],
  resources = globs('templates/ensime/*.mustache'),
  dependencies = [
    ':ide_gen',
    '3rdparty/python/twitter/commons:twitter.common.collections',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:generator',
    'src/python/pants/util:dirutil',
  ],
)

python_library(
  name = 'export',
  sources = ['export.py'],
  dependencies = [
    ':ide_gen',
    '3rdparty/python/twitter/commons:twitter.common.collections',
    'src/python/pants/backend/core/targets:all',
    'src/python/pants/backend/core/tasks:console_task',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/backend/jvm/targets:scala',
    'src/python/pants/backend/jvm:ivy_utils',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:exceptions',
  ],
)

python_library(
  name = 'filedeps',
  sources = ['filedeps.py'],
  dependencies = [
    'src/python/pants/backend/core/tasks:console_task',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/backend/jvm/targets:scala',
    'src/python/pants/backend/core/targets:common',
    'src/python/pants/base:build_environment',
  ],
)

python_library(
  name = 'ide_gen',
  sources = ['ide_gen.py'],
  dependencies = [
    '3rdparty/python/twitter/commons:twitter.common.collections',
    'src/python/pants/backend/core/tasks:task',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/backend/jvm/targets:scala',
    'src/python/pants/backend/jvm/tasks:jvm_tool_task_mixin',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:exceptions',
    'src/python/pants:binary_util',
    'src/python/pants/util:dirutil',
  ],
)

python_library(
  name = 'idea_gen',
  sources = ['idea_gen.py'],
  resources = globs('templates/idea/*.mustache'),
  dependencies = [
    ':ide_gen',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:generator',
    'src/python/pants/backend/core/targets:common',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/backend/jvm/targets:scala',
    'src/python/pants/backend/jvm/tasks:common',
    'src/python/pants/backend/python/targets:python',
    'src/python/pants/util:dirutil',
  ],
)

