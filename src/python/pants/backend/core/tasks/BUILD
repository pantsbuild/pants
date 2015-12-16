# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

target(
  name = 'all',
  dependencies = [
    ':builddictionary',
    ':dependees',
    ':filter',
    ':scm_publish',
  ]
)

python_library(
  name = 'builddictionary',
  sources = ['builddictionary.py'],
  resource_targets = [
    ':builddictionary_resources',
  ],
  dependencies = [
    ':reflect',
    '3rdparty/python:docutils',
    '3rdparty/python:setuptools',
    '3rdparty/python/twitter/commons:twitter.common.collections',
    'src/python/pants/backend/python:python_requirements',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:build_manual',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:generator',
    'src/python/pants/build_graph',
    'src/python/pants/goal',
    'src/python/pants/task',
    'src/python/pants/util:dirutil',
  ],
)

resources(
  name = 'builddictionary_resources',
  sources = globs('templates/builddictionary/*.mustache'),
)

python_library(
  name = 'dependees',
  sources = ['dependees.py'],
  dependencies = [
    'src/python/pants/backend/graph_info/tasks',
    'src/python/pants/base:deprecated',
  ],
)

python_library(
  name = 'filter',
  sources = ['filter.py'],
  dependencies = [
    'src/python/pants/backend/graph_info/tasks',
    'src/python/pants/base:deprecated',
  ],
)

python_library(
  name = 'reflect',
  sources = ['reflect.py'],
  dependencies = [
    '3rdparty/python:docutils',
    '3rdparty/python:six',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:build_manual',
    'src/python/pants/base:generator',
    'src/python/pants/build_graph',
    'src/python/pants/goal',
    'src/python/pants/help',
    'src/python/pants/option',
  ],
)

python_library(
  name = 'scm_publish',
  sources = ['scm_publish.py'],
  dependencies = [
    'src/python/pants/base:deprecated',
    'src/python/pants/task',
  ],
)
