# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name='artifact',
  sources=['artifact.py'],
  dependencies = [
    '3rdparty/python:six',
    ':repository',
    'src/python/pants/base:payload_field',
  ],
)

python_library(
  name='jar_dependency_utils',
  sources=['jar_dependency_utils.py'],
  dependencies = [
    'src/python/pants/util:memo',
  ],
)

python_library(
  name='plugin',
  sources=['__init__.py', 'register.py'],
  dependencies = [
    ':artifact',
    ':ossrh_publication_metadata',
    ':repository',
    ':scala_artifact',
    'src/python/pants/backend/jvm/subsystems:jar_dependency_management',
    'src/python/pants/backend/jvm/subsystems:scala_platform',
    'src/python/pants/backend/jvm/subsystems:shader',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/backend/jvm/targets:scala',
    'src/python/pants/backend/jvm/tasks/jvm_compile:jvm_classpath_publisher',
    'src/python/pants/backend/jvm/tasks/jvm_compile:zinc',
    'src/python/pants/backend/jvm/tasks:benchmark_run',
    'src/python/pants/backend/jvm/tasks:binary_create',
    'src/python/pants/backend/jvm/tasks:bootstrap_jvm_tools',
    'src/python/pants/backend/jvm/tasks:bundle_create',
    'src/python/pants/backend/jvm/tasks:check_published_deps',
    'src/python/pants/backend/jvm/tasks:detect_duplicates',
    'src/python/pants/backend/jvm/tasks:ivy_imports',
    'src/python/pants/backend/jvm/tasks:ivy_resolve',
    'src/python/pants/backend/jvm/tasks:jar_create',
    'src/python/pants/backend/jvm/tasks:jar_publish',
    'src/python/pants/backend/jvm/tasks:javadoc_gen',
    'src/python/pants/backend/jvm/tasks:junit_run',
    'src/python/pants/backend/jvm/tasks:jvm_dependency_check',
    'src/python/pants/backend/jvm/tasks:jvm_dependency_usage',
    'src/python/pants/backend/jvm/tasks:jvm_platform_analysis',
    'src/python/pants/backend/jvm/tasks:jvm_run',
    'src/python/pants/backend/jvm/tasks:nailgun_task',
    'src/python/pants/backend/jvm/tasks:prepare_resources',
    'src/python/pants/backend/jvm/tasks:prepare_services',
    'src/python/pants/backend/jvm/tasks:run_jvm_prep_command',
    'src/python/pants/backend/jvm/tasks:scala_repl',
    'src/python/pants/backend/jvm/tasks:scaladoc_gen',
    'src/python/pants/backend/jvm/tasks:unpack_jars',
    'src/python/pants/base:deprecated',
    'src/python/pants/build_graph',
    'src/python/pants/goal',
    'src/python/pants/goal:task_registrar',
  ],
)

python_library(
  name='ivy_utils',
  sources=['ivy_utils.py'],
  resource_targets=[
    ':ivy_utils_resources',
  ],
  dependencies = [
    '3rdparty/python:six',
    '3rdparty/python:twitter.common.collections',
    ':jar_dependency_utils',
    'src/python/pants/backend/jvm/subsystems:jar_dependency_management',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/base:generator',
    'src/python/pants/base:revision',
    'src/python/pants/build_graph',
    'src/python/pants/ivy',
    'src/python/pants/java:util',
    'src/python/pants/util:dirutil',
    'src/python/pants/util:fileutil',
  ],
)

resources(
  name='ivy_utils_resources',
  sources=globs('templates/ivy_utils/*.mustache'),
)

python_library(
  name='repository',
  sources=['repository.py'],
)

python_library(
  name='scala_artifact',
  sources=['scala_artifact.py'],
  dependencies = [
    ':artifact',
    'src/python/pants/backend/jvm/subsystems:scala_platform',
  ],
)

python_library(
  name='ossrh_publication_metadata',
  sources=['ossrh_publication_metadata.py'],
  dependencies = [
    '3rdparty/python:six',
    ':artifact',
    'src/python/pants/base:validation',
  ],
)
