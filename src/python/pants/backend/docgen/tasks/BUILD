# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


python_library(
  name = 'tasks',
  sources = globs('*.py'),
  resource_targets = [
    ':resources',
  ],
  dependencies = [
    '3rdparty/python:Markdown',
    '3rdparty/python:Pygments',
    '3rdparty/python:docutils',
    '3rdparty/python:six',
    '3rdparty/python:twitter.common.confluence',
    'src/python/pants/backend/docgen/targets',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:generator',
    'src/python/pants/base:mustache',
    'src/python/pants/base:workunit',
    'src/python/pants/binaries:binary_util',
    'src/python/pants/build_graph',
    'src/python/pants/goal',
    'src/python/pants/help',
    'src/python/pants/option',
    'src/python/pants/task',
    'src/python/pants/util:dirutil',
  ],
)

resources(
  name = 'resources',
  sources = globs('templates/*/*.mustache'),
)
