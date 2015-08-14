# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

target(
  name = 'all',
  dependencies = [
    ':bash_completion',
    ':builddictionary',
    ':changed_target_goals',
    ':clean',
    ':common',
    ':confluence_publish',
    ':console_task',
    ':deferred_sources_mapper',
    ':dependees',
    ':filemap',
    ':filter',
    ':group_task',
    ':list_goals',
    ':listtargets',
    ':markdown_to_html',
    ':minimal_cover',
    ':noop',
    ':pathdeps',
    ':paths',
    ':reporting_server',
    ':roots',
    ':run_prep_command',
    ':scm_publish',
    ':sorttargets',
    ':targets_help',
    ':task',
    ':what_changed',
  ]
)

target(
  name = 'common',
  dependencies = [
    ':task',
    'src/python/pants/base:exceptions',
  ]
)

python_library(
  name = 'bash_completion',
  sources = ['bash_completion.py'],
  resources = globs('templates/bash_completion/*.mustache'),
  dependencies = [
    ':console_task',
    ':task',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:generator',
    'src/python/pants/goal',
    'src/python/pants/option',
    ],
  )

python_library(
  name = 'builddictionary',
  sources = ['builddictionary.py'],
  resources = globs('templates/builddictionary/*.mustache'),
  dependencies = [
    ':common',
    ':reflect',
    ':task',
    '3rdparty/python:docutils',
    '3rdparty/python:setuptools',
    '3rdparty/python/twitter/commons:twitter.common.collections',
    'src/python/pants/backend/maven_layout',
    'src/python/pants/backend/python:python_requirements',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:build_file_parser',
    'src/python/pants/base:build_manual',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:generator',
    'src/python/pants/base:target',
    'src/python/pants/goal',
    'src/python/pants/util:dirutil',
  ],
)

python_library(
  name = 'clean',
  sources = ['clean.py'],
  dependencies = [
    ':task',
    'src/python/pants/base:build_environment',
    'src/python/pants/util:dirutil',
  ],
)

python_library(
  name = 'confluence_publish',
  sources = ['confluence_publish.py'],
  dependencies = [
    '3rdparty/python/twitter/commons:twitter.common.confluence',
    ':task',
    'src/python/pants/backend/core/targets:common',
    'src/python/pants/base:exceptions',
    'src/python/pants/binaries:binary_util',
    'src/python/pants/util:dirutil',
  ],
)

python_library(
  name = 'console_task',
  sources = ['console_task.py'],
  dependencies = [
    ':common',
    'src/python/pants/util:dirutil',
  ],
)

python_library(
  name = 'deferred_sources_mapper',
  sources= ['deferred_sources_mapper.py'],
  dependencies = [
    ':common',
  ],
)

python_library(
  name = 'dependees',
  sources = ['dependees.py'],
  dependencies = [
    ':common',
    ':console_task',
    '3rdparty/python/twitter/commons:twitter.common.collections',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:target',
    'src/python/pants/backend/core/targets:common',
  ],
)

python_library(
  name = 'filemap',
  sources = ['filemap.py'],
  dependencies = [
    ':console_task',
  ],
)

python_library(
  name = 'filter',
  sources = ['filter.py'],
  dependencies = [
    ':common',
    ':console_task',
    'src/python/pants/base:address',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:cmd_line_spec_parser',
    'src/python/pants/base:target',
    'src/python/pants/util:filtering',
  ],
)

python_library(
  name = 'group_task',
  sources = ['group_task.py'],
  dependencies = [
    '3rdparty/python:six',
    ':task',
    'src/python/pants/base:build_graph',
    'src/python/pants/base:workunit',
    'src/python/pants/goal',
    'src/python/pants/option',
  ],
)

python_library(
  name = 'list_goals',
  sources = ['list_goals.py'],
  dependencies = [
    ':console_task',
    'src/python/pants/goal',
  ],
)

python_library(
  name = 'listtargets',
  sources = ['listtargets.py'],
  dependencies = [
    'src/python/pants/base:exceptions',
    ':console_task',
  ],
)

python_library(
  name = 'markdown_to_html',
  sources = ['markdown_to_html.py'],
  resources = globs('templates/markdown/*.mustache'),
  dependencies = [
    '3rdparty/python:Markdown',
    '3rdparty/python:Pygments',
    '3rdparty/python:docutils',
    '3rdparty/python:six',
    ':task',
    'src/python/pants/backend/core/targets:common',
    'src/python/pants/base:address',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:generator',
    'src/python/pants/base:workunit',
    'src/python/pants/binaries:binary_util',
    'src/python/pants/util:dirutil',
  ],
)

python_library(
  name = 'minimal_cover',
  sources = ['minimal_cover.py'],
  dependencies = [
    ':console_task',
  ],
)

python_library(
  name = 'noop',
  sources = ['noop.py'],
  dependencies = [
    ':common',
  ],
)

python_library(
  name = 'pathdeps',
  sources = ['pathdeps.py'],
  dependencies = [
    ':console_task',
  ],
)

python_library(
  name = 'paths',
  sources = ['paths.py'],
  dependencies = [
    ':console_task',
    'src/python/pants/base:exceptions',
  ],
)

python_library(
  name = 'reporting_server',
  sources = ['reporting_server.py'],
  dependencies = [
    ':task',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:run_info',
    'src/python/pants/binaries:binary_util',
    'src/python/pants/reporting',
  ],
)

python_library(
  name = 'reflect',
  sources = ['reflect.py'],
  dependencies = [
    '3rdparty/python:docutils',
    '3rdparty/python:six',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:build_manual',
    'src/python/pants/base:generator',
    'src/python/pants/base:target',
    'src/python/pants/goal:goal',
    'src/python/pants/option',
  ],
)

python_library(
  name = 'roots',
  sources = ['roots.py'],
  dependencies = [
    ':console_task',
    'src/python/pants/backend/core/targets:common',
  ],
)

python_library(
  name = 'run_prep_command',
  sources = ['run_prep_command.py'],
  dependencies = [
    ':task',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:workunit',
  ],
)

python_library(
  name = 'scm_publish',
  sources = ['scm_publish.py'],
  dependencies = [
    'src/python/pants/base:exceptions',
    'src/python/pants/option',
    'src/python/pants/scm',
  ],
)

python_library(
  name = 'sorttargets',
  sources = ['sorttargets.py'],
  dependencies = [
    ':common',
    ':console_task',
    '3rdparty/python/twitter/commons:twitter.common.util',
    'src/python/pants/base:target',
  ],
)

python_library(
  name = 'targets_help',
  sources = ['targets_help.py'],
  resources = globs('templates/targets_help/*.mustache'),
  dependencies = [
    ':builddictionary',
    ':common',
    ':console_task',
    ':reflect',
  ],
)

python_library(
  name = 'task',
  sources = ['task.py'],
  dependencies = [
    '3rdparty/python/twitter/commons:twitter.common.collections',
    'src/python/pants/base:build_invalidator',
    'src/python/pants/base:cache_manager',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:hash_utils',
    'src/python/pants/base:worker_pool',
    'src/python/pants/base:workunit',
    'src/python/pants/cache',
    'src/python/pants/ivy',
    'src/python/pants/java:executor',
    'src/python/pants/reporting',
    'src/python/pants/util:meta',
  ],
)

python_library(
  name = 'what_changed',
  sources = ['what_changed.py'],
  dependencies = [
    ':console_task',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:source_mapper',
    'src/python/pants/goal:workspace',
  ],
)

python_library(
  name='changed_target_goals',
  sources=['changed_target_goals.py'],
  dependencies=[
    ':noop',
    ':what_changed',
  ],
)
