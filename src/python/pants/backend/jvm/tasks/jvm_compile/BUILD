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
    ':jvm_dependency_analyzer',
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

python_library(
  name = 'java',
  sources = globs('java/*.py'),
  dependencies = [
    ':analysis',
    ':analysis_parser',
    ':analysis_tools',
    ':jvm_compile',
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
    ':jvm_dependency_analyzer',
    ':jvm_fingerprint_strategy',
    'src/python/pants/backend/core/tasks:group_task',
    'src/python/pants/backend/core/tasks:task',
    'src/python/pants/backend/jvm/tasks:jvm_tool_task_mixin',
    'src/python/pants/backend/jvm/tasks:nailgun_task',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:target',
    'src/python/pants/base:worker_pool',
    'src/python/pants/goal:products',
    'src/python/pants/reporting',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
  ],
)

python_library(
  name = 'jvm_fingerprint_strategy',
  sources = ['jvm_fingerprint_strategy.py'],
  dependencies = [
    'src/python/pants/base:hash_utils',
    'src/python/pants/base:target',
  ],
)

python_library(
  name = 'anonymizer',
  sources = ['anonymizer.py'],
)

python_library(
  name = 'jvm_dependency_analyzer',
  sources = ['jvm_dependency_analyzer.py'],
  dependencies = [
    '3rdparty/python/twitter/commons:twitter.common.collections',
    'src/python/pants/base:build_environment',
    'src/python/pants/backend/jvm/tasks:ivy_task_mixin',
    'src/python/pants/backend/core/targets:common',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/backend/core/tasks:common',
  ],
)

python_library(
  name = 'scala',
  sources = globs('scala/*.py') - ['anonymize.py'],
  dependencies = [
    ':analysis',
    ':analysis_parser',
    ':analysis_tools',
    ':jvm_compile',
    '3rdparty/python/twitter/commons:twitter.common.collections',
    '3rdparty/python/twitter/commons:twitter.common.lang',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:hash_utils',
    'src/python/pants/base:workunit',
    'src/python/pants/backend/jvm:jvm_tool_bootstrapper',
    'src/python/pants/backend/jvm/scala:target_platform',
    'src/python/pants/backend/jvm/targets:scala',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
  ],
)

python_binary(
  name = 'anonymize_zinc_analysis',
  entry_point = 'pants.tasks.jvm_compile.scala.anonymize_analysis:main',
  dependencies = [
    ':anonymizer',
    ':scala',
    'src/python/pants/util:dirutil',
  ],
)
