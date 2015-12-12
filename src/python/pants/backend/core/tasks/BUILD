# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

target(
  name = 'all',
  dependencies = [
    ':builddictionary',
    ':cloc',
    ':confluence_publish',
    ':dependees',
    ':filemap',
    ':filter',
    ':list_owners',
    ':listtargets',
    ':markdown_to_html',
    ':minimal_cover',
    ':pathdeps',
    ':paths',
    ':scm_publish',
    ':sorttargets',
  ]
)

python_library(
  name = 'builddictionary',
  sources = ['builddictionary.py'],
  resource_targets = [
    ':builddictionary_resources',
  ],
  dependencies = [
    ':reflect',
    '3rdparty/python:docutils',
    '3rdparty/python:setuptools',
    '3rdparty/python/twitter/commons:twitter.common.collections',
    'src/python/pants/backend/python:python_requirements',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:build_manual',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:generator',
    'src/python/pants/build_graph',
    'src/python/pants/goal',
    'src/python/pants/task',
    'src/python/pants/util:dirutil',
  ],
)

resources(
  name = 'builddictionary_resources',
  sources = globs('templates/builddictionary/*.mustache'),
)

python_library(
  name = 'cloc',
  sources = ['cloc.py'],
  dependencies = [
    'src/python/pants/base:build_environment',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:workunit',
    'src/python/pants/binaries:binary_util',
    'src/python/pants/task',
    'src/python/pants/util:contextutil',
  ],
)

python_library(
  name = 'confluence_publish',
  sources = ['confluence_publish.py'],
  dependencies = [
    '3rdparty/python/twitter/commons:twitter.common.confluence',
    'src/python/pants/backend/core/targets:doc',
    'src/python/pants/base:exceptions',
    'src/python/pants/binaries:binary_util',
    'src/python/pants/build_graph',
    'src/python/pants/task',
    'src/python/pants/util:dirutil',
  ],
)

python_library(
  name = 'dependees',
  sources = ['dependees.py'],
  dependencies = [
    ':target_filter_task_mixin',
    'src/python/pants/base:build_environment',
    'src/python/pants/task',
  ],
)

python_library(
  name = 'filemap',
  sources = ['filemap.py'],
  dependencies = [
    'src/python/pants/task',
  ],
)

python_library(
  name = 'filter',
  sources = ['filter.py'],
  dependencies = [
    ':target_filter_task_mixin',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:cmd_line_spec_parser',
    'src/python/pants/base:exceptions',
    'src/python/pants/build_graph',
    'src/python/pants/task',
    'src/python/pants/util:filtering',
  ],
)

python_library(
  name = 'listtargets',
  sources = ['listtargets.py'],
  dependencies = [
    'src/python/pants/base:exceptions',
    'src/python/pants/task',
  ],
)

python_library(
  name = 'markdown_to_html',
  sources = ['markdown_to_html.py', 'markdown_to_html_utils.py'],
  resource_targets = [
    ':markdown_to_html_resources',
  ],
  dependencies = [
    '3rdparty/python:Markdown',
    '3rdparty/python:Pygments',
    '3rdparty/python:docutils',
    '3rdparty/python:six',
    'src/python/pants/backend/core/targets:doc',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:generator',
    'src/python/pants/base:workunit',
    'src/python/pants/binaries:binary_util',
    'src/python/pants/build_graph',
    'src/python/pants/task',
    'src/python/pants/util:dirutil',
  ],
)

resources(
  name = 'markdown_to_html_resources',
  sources = globs('templates/markdown/*.mustache'),
)

python_library(
  name = 'minimal_cover',
  sources = ['minimal_cover.py'],
  dependencies = [
    'src/python/pants/task',
  ],
)

python_library(
  name = 'pathdeps',
  sources = ['pathdeps.py'],
  dependencies = [
    'src/python/pants/task',
  ],
)

python_library(
  name = 'paths',
  sources = ['paths.py'],
  dependencies = [
    'src/python/pants/base:exceptions',
    'src/python/pants/task',
    'src/python/pants/util:strutil',
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
    'src/python/pants/build_graph',
    'src/python/pants/goal',
    'src/python/pants/help',
    'src/python/pants/option',
  ],
)

python_library(
  name = 'scm_publish',
  sources = ['scm_publish.py'],
  dependencies = [
    'src/python/pants/base:deprecated',
    'src/python/pants/task',
  ],
)

python_library(
  name = 'sorttargets',
  sources = ['sorttargets.py'],
  dependencies = [
    'src/python/pants/build_graph',
    'src/python/pants/task',
  ],
)

python_library(
  name = 'target_filter_task_mixin',
  sources = ['target_filter_task_mixin.py'],
  dependencies = [
    'src/python/pants/base:exceptions',
    'src/python/pants/task',
  ]
)

python_library(
  name = 'list_owners',
  sources = ['list_owners.py'],
  dependencies = [
    'src/python/pants/build_graph',
    'src/python/pants/task',
  ],
)
