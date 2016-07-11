# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name='tasks',
  sources=[
    'findbugs.py',
  ],
  dependencies=[
    '3rdparty/python/twitter/commons:twitter.common.collections',
    'src/python/pants/backend/jvm/subsystems:shader',
    'src/python/pants/backend/jvm:jar_dependency_utils',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/backend/jvm/tasks:nailgun_task',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:workunit',
    'src/python/pants/util:dirutil',
    'src/python/pants/util:xml_parser',
  ]
)
