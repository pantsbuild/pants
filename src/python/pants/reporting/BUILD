# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'reporting',
  sources = globs('*.py', exclude=[['report.py']]),
  resources = rglobs('assets/*', 'templates/*.mustache'),
  dependencies = [
    '3rdparty/python/twitter/commons:twitter.common.threading',
    '3rdparty/python:ansicolors',
    '3rdparty/python:psutil',
    '3rdparty/python:pystache',
    '3rdparty/python:six',
    ':report',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:build_file',
    'src/python/pants/base:mustache',
    'src/python/pants/base:run_info',
    'src/python/pants/base:target',
    'src/python/pants/base:workunit',
    'src/python/pants/pantsd:process_manager',
    'src/python/pants/util:dirutil',
    'src/python/pants/subsystem',
  ]
)

python_library(
  name = 'report',
  sources = ['report.py'],
  dependencies = [
    '3rdparty/python/twitter/commons:twitter.common.threading',
  ],
)
