# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

target(
  name = 'all',
  dependencies = [
    ':analysis',
    ':analysis_parser',
    ':analysis_tools',
    ':anonymizer',
    ':jvm_classpath_publisher',
    ':jvm_compile',
    ':zinc',
  ],
)

python_library(
  name = 'analysis',
  sources = ['analysis.py'],
)

python_library(
  name = 'analysis_parser',
  sources = ['analysis_parser.py'],
  dependencies = [
    'src/python/pants/base:exceptions',
  ]
)

python_library(
  name = 'analysis_tools',
  sources = ['analysis_tools.py'],
  dependencies = [
    'src/python/pants/base:build_environment',
    'src/python/pants/util:contextutil',
  ]
)

python_library(
  name = 'compile_context',
  sources = ['compile_context.py'],
  dependencies = [
    'src/python/pants/backend/codegen/thrift/java',
    'src/python/pants/base:exceptions',
    'src/python/pants/build_graph',
    'src/python/pants/util:contextutil',
  ]
)

python_library(
  name = 'jvm_classpath_publisher',
  sources = ['jvm_classpath_publisher.py'],
  dependencies = [
    ':jvm_compile',
    'src/python/pants/backend/jvm/tasks:classpath_products',
    'src/python/pants/backend/jvm/tasks:classpath_util',
    'src/python/pants/task',
    'src/python/pants/util:dirutil',
    'src/python/pants/util:fileutil',
  ]
)

python_library(
  sources = ['jvm_compile.py'],
  dependencies = [
    ':compile_context',
    ':execution_graph',
    ':missing_dependency_finder',
    'src/python/pants/backend/jvm/subsystems:java',
    'src/python/pants/backend/jvm/subsystems:jvm_platform',
    'src/python/pants/backend/jvm/subsystems:scala_platform',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/backend/jvm/tasks:classpath_util',
    'src/python/pants/backend/jvm/tasks:jvm_dependency_analyzer',
    'src/python/pants/backend/jvm/tasks:nailgun_task',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:fingerprint_strategy',
    'src/python/pants/base:worker_pool',
    'src/python/pants/base:workunit',
    'src/python/pants/build_graph',
    'src/python/pants/goal:products',
    'src/python/pants/option',
    'src/python/pants/reporting',
    'src/python/pants/util:dirutil',
    'src/python/pants/util:fileutil',
  ],
)

python_library(
  name = 'execution_graph',
  sources = ['execution_graph.py'],
  dependencies = [
    'src/python/pants/base:worker_pool',
  ],
)

python_library(
  name = 'anonymizer',
  sources = ['anonymizer.py'],
)

python_library(
  name = 'zinc',
  sources = globs('zinc/*.py'),
  dependencies = [
    ':analysis',
    ':analysis_parser',
    ':analysis_tools',
    ':jvm_compile',
    '3rdparty/python/twitter/commons:twitter.common.collections',
    '3rdparty/python:six',
    'src/python/pants/java/jar',
    'src/python/pants/backend/jvm/subsystems:java',
    'src/python/pants/backend/jvm/subsystems:scala_platform',
    'src/python/pants/backend/jvm/subsystems:shader',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/backend/jvm/targets:scala',
    'src/python/pants/backend/jvm/zinc',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:hash_utils',
    'src/python/pants/base:workunit',
    'src/python/pants/java/distribution',
    'src/python/pants/option',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'src/python/pants/util:memo',
  ],
)

python_binary(
  name = 'anonymize_zinc_analysis',
  source = 'zinc/bin/anonymize_analysis.py',
  dependencies = [
    ':anonymizer',
    ':zinc',
    'src/python/pants/util:dirutil',
  ],
)

python_library(
  name = 'missing_dependency_finder',
  sources = [
    'class_not_found_error_patterns.py',
    'missing_dependency_finder.py'
  ],
  dependencies = [
    '3rdparty/python:ansicolors',
    '3rdparty/python/twitter/commons:twitter.common.collections',
  ],
)
