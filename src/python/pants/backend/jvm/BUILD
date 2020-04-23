# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name='argfile',
  sources=['argfile.py'],
  dependencies=[
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
  ],
  tags = {"partially_type_checked"},
)

python_library(
  name='artifact',
  sources=['artifact.py'],
  dependencies=[
    ':repository',
    'src/python/pants/base:hash_utils',
    'src/python/pants/base:payload_field',
  ],
  tags = {"partially_type_checked"},
)

python_library(
  name='plugin',
  sources=['__init__.py', 'register.py'],
  dependencies=[
    ':artifact',
    ':ossrh_publication_metadata',
    ':repository',
    ':scala_artifact',
    'src/python/pants/backend/jvm/subsystems:jar_dependency_management',
    'src/python/pants/backend/jvm/subsystems:shader',
    'src/python/pants/backend/jvm/targets:all',
    'src/python/pants/backend/jvm/tasks:all',
    'src/python/pants/base:deprecated',
    'src/python/pants/build_graph',
    'src/python/pants/goal',
    'src/python/pants/goal:task_registrar',
    'src/python/pants/java/jar',
  ],
  tags = {'partially_type_checked'},
)

python_library(
  name='ivy_utils',
  sources=['ivy_utils.py'],
  dependencies=[
    ':ivy_utils_resources',
    'src/python/pants/backend/jvm/subsystems:jar_dependency_management',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:deprecated',
    'src/python/pants/base:generator',
    'src/python/pants/base:revision',
    'src/python/pants/build_graph',
    'src/python/pants/ivy',
    'src/python/pants/java:util',
    'src/python/pants/java/jar',
    'src/python/pants/util:dirutil',
    'src/python/pants/util:fileutil',
    'src/python/pants/util:ordered_set',
  ],
  tags = {"partially_type_checked"},
)

resources(
  name='ivy_utils_resources',
  sources=['templates/ivy_utils/*.mustache'],
)

python_library(
  name='repository',
  sources=['repository.py'],
  tags = {"partially_type_checked"},
)

python_library(
  name='scala_artifact',
  sources=['scala_artifact.py'],
  dependencies=[
    ':artifact',
    'src/python/pants/backend/jvm/subsystems:scala_platform',
    'src/python/pants/util:memo',
  ],
  tags = {'partially_type_checked'},
)

python_library(
  name='ossrh_publication_metadata',
  sources=['ossrh_publication_metadata.py'],
  dependencies=[
    ':artifact',
    'src/python/pants/base:validation',
  ],
  tags = {"partially_type_checked"},
)

python_library(
  name='target_types',
  sources=['target_types.py'],
  dependencies=[
    'src/python/pants/backend/jvm/subsystems:shader',
    'src/python/pants/engine:addresses',
    'src/python/pants/engine:target',
    'src/python/pants/java/jar',
  ],
  tags = {"type_checked"},
)
