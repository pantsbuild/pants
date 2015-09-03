# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

target(
  name='tasks',
  dependencies=[
    ':bash_completion',
    ':markdown_to_html',
    'mutex_task_mixin',
    ':scm_publish',
  ],
)

python_tests(
  name='bash_completion',
  sources=['test_bash_completion.py'],
  coverage=['pants.backend.core.tasks.bash_completion'],
  dependencies=[
    '3rdparty/python:mock',
    'src/python/pants/backend/core/tasks:bash_completion',
    'tests/python/pants_test/tasks:task_test_base',
  ]
)

python_tests(
  name='cache_cleanup',
  sources=['test_cache_cleanup.py'],
  coverage=['pants.backend.core.tasks.bash_completion'],
  dependencies=[
    'src/python/pants/backend/jvm/tasks/jvm_compile:java',
    'src/python/pants/util:dirutil',
    'tests/python/pants_test:int-test',
    'src/python/pants/util:contextutil',
  ]
)

python_tests(
  name = 'markdown_to_html',
  sources = ['test_markdown_to_html.py'],
  dependencies = [
    '3rdparty/python:beautifulsoup4',
    '3rdparty/python:mock',
    'src/python/pants/backend/core/targets:common',
    'src/python/pants/backend/core/tasks:markdown_to_html',
    'src/python/pants/base:exceptions',
    'tests/python/pants_test/tasks:task_test_base',
  ],
  coverage=[
    'pants.backend.core.tasks.markdown_to_html',
  ]
)

python_tests(
  name='markdown_to_html_integration',
  sources=['test_markdown_to_html_integration.py'],
  dependencies=[
    'src/python/pants/base:build_environment',
    'src/python/pants/util:dirutil',
    'tests/python/pants_test:int-test',
  ],
  coverage=[
    'pants.backend.core.tasks.markdown_to_html',
  ]
)

python_tests(
  name='mutex_task_mixin',
  sources=['test_mutex_task_mixin.py'],
  dependencies=[
    'src/python/pants/backend/core/tasks:mutex_task_mixin',
    'src/python/pants/base:target',
    'src/python/pants/util:contextutil',
    'tests/python/pants_test:base_test',
  ]
)

python_tests(
  name='scm_publish',
  sources=['test_scm_publish.py'],
  coverage=['pants.backend.core.tasks.scm_publish'],
  dependencies=[
    '3rdparty/python:mock',
    'src/python/pants/backend/core/tasks:scm_publish',
  ]
)
