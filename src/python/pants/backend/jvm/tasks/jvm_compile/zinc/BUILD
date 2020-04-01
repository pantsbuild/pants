# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  dependencies = [
    'src/python/pants/backend/jvm/subsystems:java',
    'src/python/pants/backend/jvm/subsystems:jvm_platform',
    'src/python/pants/backend/jvm/subsystems:scala_platform',
    'src/python/pants/backend/jvm/subsystems:shader',
    'src/python/pants/backend/jvm/subsystems:zinc',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/backend/jvm/targets:scala',
    'src/python/pants/backend/jvm/tasks/jvm_compile:jvm_compile',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:hash_utils',
    'src/python/pants/base:workunit',
    'src/python/pants/java/distribution',
    'src/python/pants/java/jar',
    'src/python/pants/option',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'src/python/pants/util:enums',
    'src/python/pants/util:logging',
    'src/python/pants/util:memo',
    'src/python/pants/util:strutil',
  ],
  tags = {"partially_type_checked"},
)
