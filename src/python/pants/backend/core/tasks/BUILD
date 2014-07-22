# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

dependencies(
  name = 'all',
  dependencies = [
    ':build_lint',
    ':builddictionary',
    ':check_exclusives',
    ':clean',
    ':common',
    ':confluence_publish',
    ':console_task',
    ':dependees',
    ':filemap',
    ':filter',
    ':group_task',
    ':list_goals',
    ':listtargets',
    ':markdown_to_html',
    ':minimal_cover',
    ':pathdeps',
    ':paths',
    ':prepare_resources',
    ':reporting_server',
    ':roots',
    ':scm_publish',
    ':sorttargets',
    ':targets_help',
    ':task',
    ':what_changed',
  ]
)

python_library(
  name = 'common',
  sources = ['__init__.py'],
  dependencies = [
    ':task',
    'src/python/pants/base:exceptions',
  ]
)

python_library(
  name = 'build_lint',
  sources = ['build_lint.py'],
  dependencies = [
    pants(':common'),
  ],
)

python_library(
  name = 'builddictionary',
  sources = ['builddictionary.py'],
  resources = globs('templates/builddictionary/*.mustache'),
  dependencies = [
    pants(':common'),
    pants('3rdparty/python:setuptools'),
    pants('3rdparty/python/twitter/commons:twitter.common.dirutil'),
    pants('src/python/pants/backend/core/tasks:task'),
    pants('src/python/pants/backend/maven_layout'),
    pants('src/python/pants/backend/python:python_requirements'),
    pants('src/python/pants/base:build_environment'),
    pants('src/python/pants/base:build_file_parser'),
    pants('src/python/pants/base:build_manual'),
    pants('src/python/pants/base:config'),
    pants('src/python/pants/base:exceptions'),
    pants('src/python/pants/base:generator'),
    pants('src/python/pants/goal:option_helpers'),
    pants('src/python/pants/goal:phase'),
    pants('src/python/pants/util:dirutil'),
  ],
)

python_library(
  name = 'check_exclusives',
  sources = ['check_exclusives.py'],
  dependencies = [
    pants(':common'),
    pants('3rdparty/python/twitter/commons:twitter.common.collections'),
    pants('src/python/pants/base:target'),
    pants('src/python/pants/backend/core/targets:common'),
  ],
)

python_library(
  name = 'clean',
  sources = ['clean.py'],
  dependencies = [
    pants(':console_task'),
    pants('3rdparty/python:python-daemon'),
    pants('src/python/pants/base:build_environment'),
    pants('src/python/pants/base:config'),
    pants('src/python/pants/util:dirutil'),
  ],
)

python_library(
  name = 'confluence_publish',
  sources = ['confluence_publish.py'],
  dependencies = [
    pants(':common'),
    pants('3rdparty/python/twitter/commons:twitter.common.confluence'),
    pants('src/python/pants/backend/core/targets:common'),
    pants('src/python/pants:binary_util'),
    pants('src/python/pants/util:dirutil'),

  ],
)

python_library(
  name = 'console_task',
  sources = ['console_task.py'],
  dependencies = [
    pants(':common'),
  ],
)

python_library(
  name = 'dependees',
  sources = ['dependees.py'],
  dependencies = [
    pants(':common'),
    pants(':console_task'),
    pants('3rdparty/python/twitter/commons:twitter.common.collections'),
    pants('src/python/pants/base:build_environment'),
    pants('src/python/pants/base:build_file'),
    pants('src/python/pants/base:target'),
    pants('src/python/pants/backend/core/targets:common'),
  ],
)

python_library(
  name = 'filemap',
  sources = ['filemap.py'],
  dependencies = [
    pants(':console_task'),
  ],
)

python_library(
  name = 'filter',
  sources = ['filter.py'],
  dependencies = [
    pants(':common'),
    pants(':console_task'),
    pants('src/python/pants/base:address'),
    pants('src/python/pants/base:build_environment'),
    pants('src/python/pants/base:cmd_line_spec_parser'),
    pants('src/python/pants/base:target'),
  ],
)

python_library(
  name = 'group_task',
  sources = ['group_task.py'],
  dependencies = [
    pants(':check_exclusives'),
    pants(':task'),
    pants('3rdparty/python/twitter/commons:twitter.common.lang'),
    pants('3rdparty/python/twitter/commons:twitter.common.collections'),
    pants('src/python/pants/base:build_graph'),
    pants('src/python/pants/base:workunit'),
  ],
)

python_library(
  name = 'list_goals',
  sources = ['list_goals.py'],
  dependencies = [
    pants(':console_task'),
    pants('src/python/pants/goal'),
  ],
)

python_library(
  name = 'listtargets',
  sources = ['listtargets.py'],
  dependencies = [
    pants('src/python/pants/base:exceptions'),
    pants(':console_task'),
  ],
)

python_library(
  name = 'markdown_to_html',
  sources = ['markdown_to_html.py'],
  dependencies = [
    pants('3rdparty/python:Markdown'),
    pants('3rdparty/python:Pygments'),
    pants(':common'),
    pants('src/python/pants/base:address'),
    pants('src/python/pants/base:build_environment'),
    pants('src/python/pants/base:target'),
    pants('src/python/pants/backend/core/targets:common'),
    pants('src/python/pants:binary_util'),
    pants('src/python/pants/util:dirutil'),
  ],
)

python_library(
  name = 'minimal_cover',
  sources = ['minimal_cover.py'],
  dependencies = [
    pants(':console_task'),
  ],
)

python_library(
  name = 'pathdeps',
  sources = ['pathdeps.py'],
  dependencies = [
    pants(':console_task'),
  ],
)

python_library(
  name = 'paths',
  sources = ['paths.py'],
  dependencies = [
    pants(':common'),
    pants(':console_task'),
    pants('3rdparty/python/twitter/commons:twitter.common.lang'),
    pants('src/python/pants/base:build_environment'),
    pants('src/python/pants/base:address'),
    pants('src/python/pants/base:target'),
  ],
)

python_library(
  name = 'prepare_resources',
  sources = ['prepare_resources.py'],
  dependencies = [
    pants(':common'),
    pants('src/python/pants/goal:products'),
    pants('src/python/pants/util:dirutil'),
  ],
)

python_library(
  name = 'reporting_server',
  sources = ['reporting_server.py'],
  dependencies = [
    pants(':console_task'),
    pants('src/python/pants/base:build_environment'),
    pants('src/python/pants/base:run_info'),
    pants('src/python/pants/reporting'),
  ],
)

python_library(
  name = 'roots',
  sources = ['roots.py'],
  dependencies = [
    pants(':console_task'),
    pants('src/python/pants/backend/core/targets:common'),
  ],
)

python_library(
  name = 'scm_publish',
  sources = ['scm_publish.py'],
  dependencies = [
    pants(':common'),
  ],
)

python_library(
  name = 'sorttargets',
  sources = ['sorttargets.py'],
  dependencies = [
    pants(':common'),
    pants(':console_task'),
    pants('3rdparty/python/twitter/commons:twitter.common.util'),
    pants('src/python/pants/base:target'),
  ],
)

python_library(
  name = 'targets_help',
  sources = ['targets_help.py'],
  dependencies = [
    pants(':common'),
    pants(':console_task'),
    pants('src/python/pants/base:target'),
    pants('src/python/pants/backend/core/targets:common'),
  ],
)

python_library(
  name = 'task',
  sources = ['task.py'],
  dependencies = [
    pants('3rdparty/python/twitter/commons:twitter.common.collections'),
    pants('src/python/pants/base:build_invalidator'),
    pants('src/python/pants/base:cache_manager'),
    pants('src/python/pants/base:config'),
    pants('src/python/pants/base:exceptions'),
    pants('src/python/pants/base:hash_utils'),
    pants('src/python/pants/base:worker_pool'),
    pants('src/python/pants/base:workunit'),
    pants('src/python/pants/cache'),
    pants('src/python/pants/ivy'),
    pants('src/python/pants/java:executor'),
    pants('src/python/pants/reporting'),
  ],
)

python_library(
  name = 'what_changed',
  sources = ['what_changed.py'],
  dependencies = [
    pants('3rdparty/python/twitter/commons:twitter.common.lang'),
    pants(':common'),
    pants(':console_task'),
    pants('src/python/pants/base:build_environment'),
    pants('src/python/pants/base:build_file'),
    pants('src/python/pants/base:target'),
    pants('src/python/pants/scm'),
  ],
)
