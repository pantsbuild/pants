# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'all',
  dependencies = [
    ':analysis',
    ':analysis_parser',
    ':analysis_tools',
    ':java',
    ':jvm_compile',
    ':anonymizer',
    ':jvm_dependency_analyzer',
    ':scala',
    ':anonymize_zinc_analysis',
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
    pants('src/python/pants/base:exceptions'),
  ]
)

python_library(
  name = 'analysis_tools',
  sources = ['analysis_tools.py'],
  dependencies = [
    pants('src/python/pants/base:build_environment'),
    pants('src/python/pants/util:contextutil'),
  ]
)

python_library(
  name = 'java',
  sources = globs('java/*.py'),
  dependencies = [
    pants(':analysis'),
    pants(':analysis_tools'),
    pants(':jvm_compile'),
    pants('src/python/pants/base:build_environment'),
    pants('src/python/pants/base:exceptions'),
    pants('src/python/pants/base:target'),
    pants('src/python/pants/base:workunit'),
    pants('src/python/pants/util:dirutil'),
  ],
)

python_library(
  name = 'jvm_compile',
  sources = ['jvm_compile.py'],
  dependencies = [
    pants(':jvm_dependency_analyzer'),
    pants('src/python/pants/backend/core/tasks:group_task'),
    pants('src/python/pants/backend/core/tasks:task'),
    pants('src/python/pants/backend/jvm/tasks:jvm_tool_task_mixin'),
    pants('src/python/pants/backend/jvm/tasks:nailgun_task'),
    pants('src/python/pants/base:build_environment'),
    pants('src/python/pants/base:target'),
    pants('src/python/pants/base:worker_pool'),
    pants('src/python/pants/goal:products'),
    pants('src/python/pants/reporting'),
    pants('src/python/pants/util:contextutil'),
    pants('src/python/pants/util:dirutil'),
  ],
)

python_library(
  name = 'anonymizer',
  sources = ['anonymizer.py'],
  dependencies = []
)

python_library(
  name = 'jvm_dependency_analyzer',
  sources = ['jvm_dependency_analyzer.py'],
  dependencies = [
    pants('3rdparty/python/twitter/commons:twitter.common.collections'),
    pants('src/python/pants/base:build_environment'),
    pants('src/python/pants/backend/jvm/tasks:ivy_task_mixin'),
    pants('src/python/pants/backend/core/targets:common'),
    pants('src/python/pants/backend/jvm/targets:jvm'),
    pants('src/python/pants/backend/core/tasks:common'),
  ],
)

python_library(
  name = 'scala',
  sources = globs('scala/*.py') - ['anonymize.py'],
  dependencies = [
    pants(':analysis'),
    pants(':analysis_parser'),
    pants(':analysis_tools'),
    pants(':jvm_compile'),
    pants('3rdparty/python/twitter/commons:twitter.common.collections'),
    pants('3rdparty/python/twitter/commons:twitter.common.lang'),
    pants('src/python/pants/base:build_environment'),
    pants('src/python/pants/base:exceptions'),
    pants('src/python/pants/base:hash_utils'),
    pants('src/python/pants/base:workunit'),
    pants('src/python/pants/backend/jvm:jvm_tool_bootstrapper'),
    pants('src/python/pants/backend/jvm/scala:target_platform'),
    pants('src/python/pants/backend/jvm/targets:scala'),
    pants('src/python/pants/util:contextutil'),
    pants('src/python/pants/util:dirutil'),
  ],
)

python_binary(
  name = 'anonymize_zinc_analysis',
  entry_point = 'pants.tasks.jvm_compile.scala.anonymize_analysis:main',
  dependencies = [
    pants(':anonymizer'),
    pants(':scala'),
    pants('src/python/pants/util:dirutil'),
  ],
)
