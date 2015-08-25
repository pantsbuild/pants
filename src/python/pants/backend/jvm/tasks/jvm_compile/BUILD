# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

target(
  name = 'all',
  dependencies = [
    ':analysis',
    ':analysis_parser',
    ':analysis_tools',
    ':anonymizer',
    ':java',
    ':jvm_compile',
    ':jvm_dependency_check',
    ':scala',
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

# TODO(Eric Ayers) Create a BUILD file in the java/ subdirectory?
python_library(
  name = 'java',
  sources = globs('java/*.py'),
  dependencies = [
    '3rdparty/python:six',
    ':analysis',
    ':analysis_parser',
    ':analysis_tools',
    ':jvm_compile',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:target',
    'src/python/pants/base:workunit',
    'src/python/pants/util:dirutil',
  ],
)

python_library(
  name = 'jvm_compile',
  sources = ['jvm_compile.py'],
  dependencies = [
    ':jvm_compile_global_strategy',
    ':jvm_compile_isolated_strategy',
    'src/python/pants/backend/core/tasks:group_task',
    'src/python/pants/backend/jvm/subsystems:jvm_platform',
    'src/python/pants/backend/jvm/tasks:nailgun_task',
    'src/python/pants/goal:products',
    'src/python/pants/option',
    'src/python/pants/reporting',
    'src/python/pants/util:dirutil',
    'src/python/pants/base:fingerprint_strategy',
  ],
)

python_library(
  name = 'jvm_compile_global_strategy',
  sources = ['jvm_compile_global_strategy.py'],
  dependencies = [
    '3rdparty/python/twitter/commons:twitter.common.collections',
    ':jvm_compile_strategy',
    ':resource_mapping',
    'src/python/pants/backend/jvm/tasks:classpath_util',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:target',
    'src/python/pants/base:worker_pool',
    'src/python/pants/option',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
  ],
)

python_library(
  name = 'jvm_compile_isolated_strategy',
  sources = ['jvm_compile_isolated_strategy.py'],
  dependencies = [
    ':execution_graph',
    ':jvm_compile_strategy',
    ':resource_mapping',
    'src/python/pants/backend/jvm/tasks:classpath_util',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:target',
    'src/python/pants/base:worker_pool',
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
  name = 'jvm_compile_strategy',
  sources = ['jvm_compile_strategy.py'],
  dependencies = [
    '3rdparty/python/twitter/commons:twitter.common.collections',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:build_environment',
    'src/python/pants/util:dirutil',
    'src/python/pants/util:contextutil',
  ],
)

python_library(
  name = 'resource_mapping',
  sources = ['resource_mapping.py'],
)

python_library(
  name = 'anonymizer',
  sources = ['anonymizer.py'],
)

python_library(
  name = 'jvm_dependency_check',
  sources = ['jvm_dependency_check.py'],
  dependencies = [
    '3rdparty/python/twitter/commons:twitter.common.collections',
    'src/python/pants/backend/core/tasks:task',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:build_graph',
    'src/python/pants/base:exceptions',
    'src/python/pants/backend/jvm/tasks:ivy_task_mixin',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/backend/jvm/targets:scala',
    'src/python/pants/util:memo',
  ],
)

python_library(
  name = 'scala',
  sources = globs('scala/*.py'),
  dependencies = [
    '3rdparty/python/twitter/commons:twitter.common.collections',
    '3rdparty/python:six',
    '3rdparty/python:zincutils',
    ':analysis',
    ':analysis_parser',
    ':analysis_tools',
    ':jvm_compile',
    'src/python/pants/backend/jvm/subsystems:scala_platform',
    'src/python/pants/backend/jvm/targets:scala',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:hash_utils',
    'src/python/pants/base:workunit',
    'src/python/pants/java/jar:shader',
    'src/python/pants/option',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
  ],
)

python_binary(
  name = 'anonymize_zinc_analysis',
  source = 'scala/bin/anonymize_analysis.py',
  dependencies = [
    ':anonymizer',
    ':scala',
    'src/python/pants/util:dirutil',
  ],
)
