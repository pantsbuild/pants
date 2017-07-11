# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  sources=[
    'errorprone.py',
  ],
  dependencies=[
    '3rdparty/python/twitter/commons:twitter.common.collections',
    'src/python/pants/backend/jvm/subsystems:shader',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/backend/jvm/tasks:nailgun_task',
    'src/python/pants/java/jar',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:workunit',
    'src/python/pants/util:dirutil',
  ]
)
