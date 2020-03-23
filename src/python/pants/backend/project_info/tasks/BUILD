# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

target(
  name = 'all',
  dependencies = [
    ':dependencies',
    ':depmap',
    ':export',
    ':export_dep_as_jar',
    ':filedeps',
    ':idea_plugin_gen',
  ],
)

python_library(
  name = 'dependencies',
  sources = ['dependencies.py'],
  dependencies = [
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:payload_field',
    'src/python/pants/task',
    'src/python/pants/util:ordered_set',
  ],
  tags = {"partially_type_checked"},
)

python_library(
  name = 'depmap',
  sources = ['depmap.py'],
  dependencies = [
    'src/python/pants/java/jar',
    'src/python/pants/base:exceptions',
    'src/python/pants/task',
  ],
  tags = {"partially_type_checked"},
)

python_library(
  name = 'export',
  sources = ['export.py'],
  dependencies = [
    ':export_version',
    'src/python/pants/backend/jvm/subsystems:jvm_platform',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/backend/jvm/targets:scala',
    'src/python/pants/backend/jvm/tasks:classpath_products',
    'src/python/pants/backend/jvm:ivy_utils',
    'src/python/pants/backend/python:interpreter_cache',
    'src/python/pants/backend/python/subsystems',
    'src/python/pants/backend/python/targets',
    'src/python/pants/backend/python/tasks',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:revision',
    'src/python/pants/build_graph',
    'src/python/pants/java/distribution',
    'src/python/pants/java:executor',
    'src/python/pants/task',
    'src/python/pants/util:memo',
    'src/python/pants/util:ordered_set',
  ],
  tags = {'partially_type_checked'},
)

python_library(
  name = 'export_dep_as_jar',
  sources = ['export_dep_as_jar.py'],
  dependencies = [
    ':export_version',
    'src/python/pants/backend/jvm/subsystems:jvm_platform',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/backend/jvm/targets:scala',
    'src/python/pants/backend/jvm/tasks:classpath_products',
    'src/python/pants/backend/jvm/tasks/jvm_compile:all',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:revision',
    'src/python/pants/build_graph',
    'src/python/pants/java/distribution',
    'src/python/pants/java:executor',
    'src/python/pants/task',
    'src/python/pants/util:memo',
    'src/python/pants/util:ordered_set',
  ],
  tags = {'partially_type_checked'},
)

python_library(
  name = 'export_version',
  sources = ['export_version.py'],
  tags = {"partially_type_checked"},
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
  tags = {"partially_type_checked"},
)

python_library(
  name = 'idea_plugin_gen',
  sources = ['idea_plugin_gen.py'],
  dependencies = [
    ':idea_resources',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/backend/python/targets',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:generator',
    'src/python/pants/task',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:desktop',
    'src/python/pants/util:dirutil',
  ],
  tags = {'partially_type_checked'},
)

resources(
  name = 'idea_resources',
  sources = ['templates/idea/*.mustache'],
)
