# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name = 'all',
  dependencies = [
    ':dependencies',
    ':depmap',
    ':export',
    ':export_integration',
    ':filedeps',
    ':ide_gen',
    ':idea_gen',
  ],
)

python_tests(
  name = 'dependencies',
  sources = ['test_dependencies.py'],
  dependencies = [
    'src/python/pants/backend/core/targets:common',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/backend/jvm/targets:scala',
    'src/python/pants/backend/project_info/tasks:dependencies',
    'src/python/pants/backend/python/targets:python',
    'src/python/pants/backend/python:python_requirement',
    'src/python/pants/base:exceptions',
    'tests/python/pants_test/tasks:task_test_base',
  ]
)

python_tests(
  name = 'depmap',
  sources = ['test_depmap.py'],
  dependencies = [
    'src/python/pants/backend/core:plugin',
    'src/python/pants/backend/core/targets:common',
    'src/python/pants/backend/jvm:plugin',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/backend/jvm/targets:scala',
    'src/python/pants/backend/project_info/tasks:depmap',
    'src/python/pants/backend/python:plugin',
    'src/python/pants/base:build_file_aliases',
    'src/python/pants/base:exceptions',
    'tests/python/pants_test/tasks:task_test_base',
  ]
)

python_tests(
  name = 'export',
  sources = ['test_export.py'],
  dependencies = [
    'src/python/pants/backend/core:plugin',
    'src/python/pants/backend/core/targets:common',
    'src/python/pants/backend/jvm:plugin',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/backend/jvm/targets:scala',
    'src/python/pants/backend/project_info/tasks:export',
    'src/python/pants/backend/python:plugin',
    'src/python/pants/base:exceptions',
    'tests/python/pants_test/tasks:task_test_base',
  ]
)


python_tests(
  name = 'export_integration',
  sources = ['test_export_integration.py'],
  dependencies = [
    'src/python/pants/backend/core:plugin',
    'src/python/pants/backend/core/targets:common',
    'src/python/pants/backend/python:plugin',
    'src/python/pants/backend/project_info/tasks:export',
    'tests/python/pants_test/tasks:task_test_base',
  ]
)

python_tests(
  name = 'filedeps',
  sources = ['test_filedeps.py'],
  dependencies = [
    'src/python/pants/backend/codegen:plugin',
    'src/python/pants/backend/core:plugin',
    'src/python/pants/backend/jvm:plugin',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/backend/project_info/tasks:filedeps',
    'tests/python/pants_test/tasks:task_test_base',
  ],
)

python_tests(
  name = 'ide_gen',
  sources = ['test_ide_gen.py'],
  dependencies = [
    'src/python/pants/backend/project_info/tasks:ide_gen',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/base:source_root',
    'tests/python/pants_test:base_test',
  ]
)

python_tests(
  name = 'idea_gen',
  sources = ['test_idea_gen.py'],
  dependencies = [
    'src/python/pants/backend/core/targets:common',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/backend/project_info/tasks:ide_gen',
    'src/python/pants/backend/project_info/tasks:idea_gen',
    'src/python/pants/base:source_root',
    'tests/python/pants_test:base_test',
  ]
)

