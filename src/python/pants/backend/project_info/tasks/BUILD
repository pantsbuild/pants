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
    ':idea_plugin_gen',
  ],
)

python_library(
  name = 'dependencies',
  sources = ['dependencies.py'],
  dependencies = [
    '3rdparty/python/twitter/commons:twitter.common.collections',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:payload_field',
    'src/python/pants/task',
  ],
)

python_library(
  name = 'depmap',
  sources = ['depmap.py'],
  dependencies = [
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/base:exceptions',
    'src/python/pants/task',
  ],
)

python_library(
  name = 'eclipse_gen',
  sources = ['eclipse_gen.py'],
  resource_targets = [
    ':eclipse_gen_resources',
  ],
  dependencies = [
    ':ide_gen',
    '3rdparty/python/twitter/commons:twitter.common.collections',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:generator',
    'src/python/pants/util:dirutil',
  ],
)

resources(
  name = 'eclipse_gen_resources',
  sources = globs('templates/eclipse/*.mustache', 'templates/eclipse/*.prefs'),
)

python_library(
  name = 'ensime_gen',
  sources = ['ensime_gen.py'],
  resource_targets = [
    ':ensime_gen_resources',
  ],
  dependencies = [
    ':ide_gen',
    '3rdparty/python/twitter/commons:twitter.common.collections',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:generator',
    'src/python/pants/util:dirutil',
  ],
)

resources(
  name = 'ensime_gen_resources',
  sources = globs('templates/ensime/*.mustache'),
)

python_library(
  name = 'export',
  sources = ['export.py'],
  dependencies = [
    '3rdparty/python/twitter/commons:twitter.common.collections',
    '3rdparty/python:pex',
    'src/python/pants/backend/jvm/subsystems:jvm_platform',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/backend/jvm/targets:scala',
    'src/python/pants/backend/jvm/tasks:classpath_products',
    'src/python/pants/backend/jvm/tasks:ivy_task_mixin',
    'src/python/pants/backend/jvm:ivy_utils',
    'src/python/pants/backend/python/targets:python',
    'src/python/pants/backend/python/tasks:python',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:revision',
    'src/python/pants/build_graph',
    'src/python/pants/java/distribution',
    'src/python/pants/java:executor',
    'src/python/pants/option',
    'src/python/pants/task',
    'src/python/pants/util:memo',
  ],
)

python_library(
  name = 'filedeps',
  sources = ['filedeps.py'],
  dependencies = [
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/backend/jvm/targets:scala',
    'src/python/pants/base:build_environment',
    'src/python/pants/build_graph',
    'src/python/pants/task',
  ],
)

python_library(
  name = 'ide_gen',
  sources = ['ide_gen.py'],
  dependencies = [
    '3rdparty/python/twitter/commons:twitter.common.collections',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/backend/jvm/targets:scala',
    'src/python/pants/backend/jvm/tasks:classpath_products',
    'src/python/pants/backend/jvm/tasks:ivy_task_mixin',
    'src/python/pants/backend/jvm/tasks:nailgun_task',
    'src/python/pants/base:build_environment',
    'src/python/pants/build_graph',
    'src/python/pants/base:exceptions',
    'src/python/pants/binaries:binary_util',
    'src/python/pants/util:dirutil',
  ],
)

python_library(
  name = 'idea_gen',
  sources = ['idea_gen.py'],
  resource_targets = [
    ':idea_resources',
  ],
  dependencies = [
    ':ide_gen',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:generator',
    'src/python/pants/scm:git',
    'src/python/pants/util:dirutil',
  ],
)

python_library(
  name = 'idea_plugin_gen',
  sources = ['idea_plugin_gen.py'],
  resource_targets = [
    ':idea_resources',
  ],
  dependencies = [
    ':ide_gen',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:generator',
    'src/python/pants/scm:git',
    'src/python/pants/util:dirutil',
  ],
)

resources(
  name = 'idea_resources',
  sources = globs('templates/idea/*.mustache'),
)
