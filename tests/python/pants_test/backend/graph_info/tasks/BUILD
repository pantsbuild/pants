# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_tests(
  name = 'dependees',
  sources = ['test_dependees.py'],
  dependencies = [
    'src/python/pants/backend/codegen/thrift/java',
    'src/python/pants/backend/graph_info/tasks',
    'src/python/pants/java/jar',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/backend/python/targets',
    'src/python/pants/build_graph',
    'src/python/pants/testutil:task_test_base',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = 'filemap',
  sources = ['test_filemap.py'],
  dependencies = [
    'src/python/pants/backend/graph_info/tasks',
    'src/python/pants/backend/python/targets',
    'src/python/pants/build_graph',
    'src/python/pants/testutil:task_test_base',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = 'filter',
  sources = ['test_filter.py'],
  dependencies = [
    'src/python/pants/backend/docgen/targets',
    'src/python/pants/backend/graph_info/tasks',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/backend/python/targets',
    'src/python/pants/base:exceptions',
    'src/python/pants/build_graph',
    'src/python/pants/testutil:task_test_base',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name = 'minimal_cover',
  sources = ['test_minimal_cover.py'],
  dependencies = [
    'src/python/pants/backend/graph_info/tasks',
    'src/python/pants/backend/python/targets',
    'src/python/pants/build_graph',
    'src/python/pants/testutil:task_test_base',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name='paths',
  sources=['test_paths.py'],
  dependencies=[
    'src/python/pants/backend/graph_info/tasks',
    'src/python/pants/base:exceptions',
    'src/python/pants/testutil:task_test_base',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name='paths_integration',
  sources=['test_paths_integration.py'],
  dependencies=[
    'src/python/pants/testutil:int-test',
    'testprojects/src/python:python_targets_directory',
  ],
  tags = {'integration', 'partially_type_checked'},
)

python_tests(
  name = 'sort_targets',
  sources = ['test_sort_targets.py'],
  dependencies = [
    'src/python/pants/backend/graph_info/tasks',
    'src/python/pants/backend/python/targets',
    'src/python/pants/build_graph',
    'src/python/pants/testutil:task_test_base',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name='target_filter_task_mixin',
  sources=['test_target_filter_task_mixin.py'],
  dependencies=[
    'src/python/pants/backend/graph_info/tasks',
    'src/python/pants/build_graph',
    'src/python/pants/testutil:task_test_base',
  ],
  tags = {"partially_type_checked"},
)
