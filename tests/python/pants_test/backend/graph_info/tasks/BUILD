# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


python_tests(
  name='cloc',
  sources=['test_cloc.py'],
  coverage=['pants.backend.graph_info.tasks.cloc'],
  dependencies = [
    'src/python/pants/backend/graph_info/tasks',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/backend/python/targets:python',
    'src/python/pants/base:build_environment',
    'tests/python/pants_test/tasks:task_test_base',
  ],
)

python_tests(
  name = 'dependees',
  sources = ['test_dependees.py'],
  dependencies = [
    'src/python/pants/backend/codegen/targets:java',
    'src/python/pants/backend/graph_info/tasks',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/backend/jvm/targets:jvm',
    'src/python/pants/backend/jvm/targets:scala',
    'src/python/pants/backend/python/targets:python',
    'src/python/pants/build_graph',
    'tests/python/pants_test/tasks:task_test_base',
  ],
)

python_tests(
  name = 'pathdeps',
  sources = ['test_pathdeps.py'],
  dependencies = [
    'src/python/pants/backend/graph_info/tasks',
    'tests/python/pants_test/tasks:task_test_base',
  ],
)

python_tests(
  name = 'filemap',
  sources = ['test_filemap.py'],
  dependencies = [
    'src/python/pants/backend/graph_info/tasks',
    'src/python/pants/backend/python/targets:python',
    'src/python/pants/build_graph',
    'tests/python/pants_test/tasks:task_test_base',
  ],
)

python_tests(
  name = 'filter',
  sources = ['test_filter.py'],
  dependencies = [
    'src/python/pants/backend/docgen/targets',
    'src/python/pants/backend/graph_info/tasks',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/backend/python/targets:python',
    'src/python/pants/base:exceptions',
    'src/python/pants/build_graph',
    'tests/python/pants_test/tasks:task_test_base',
  ],
)

python_tests(
  name = 'listtargets',
  sources = ['test_listtargets.py'],
  dependencies = [
    'src/python/pants/backend/graph_info/tasks',
    'src/python/pants/backend/jvm/targets:java',
    'src/python/pants/backend/jvm:artifact',
    'src/python/pants/backend/jvm:repository',
    'src/python/pants/backend/jvm:scala_artifact',
    'src/python/pants/backend/python/targets:python',
    'src/python/pants/build_graph',
    'tests/python/pants_test/tasks:task_test_base',
  ],
)

python_tests(
  name = 'list_owners',
  sources = ['test_list_owners.py'],
  dependencies = [
    'src/python/pants/backend/graph_info/tasks',
    'src/python/pants/backend/python/targets:python',
    'src/python/pants/base:exceptions',
    'src/python/pants/build_graph',
    'tests/python/pants_test/tasks:task_test_base',
  ],
)

python_tests(
  name = 'minimal_cover',
  sources = ['test_minimal_cover.py'],
  dependencies = [
    'src/python/pants/backend/graph_info/tasks',
    'src/python/pants/backend/python/targets:python',
    'src/python/pants/build_graph',
    'tests/python/pants_test/tasks:task_test_base',
  ],
)

python_tests(
  name='paths',
  sources=['test_paths.py'],
  dependencies = [
    'src/python/pants/backend/graph_info/tasks',
    'src/python/pants/base:exceptions',
    'tests/python/pants_test/tasks:task_test_base',
  ],
)

python_tests(
  name = 'sorttargets',
  sources = ['test_sorttargets.py'],
  dependencies = [
    'src/python/pants/backend/graph_info/tasks',
    'src/python/pants/backend/python/targets:python',
    'src/python/pants/build_graph',
    'tests/python/pants_test/tasks:task_test_base',
  ],
)

python_tests(
  name='target_filter_task_mixin',
  sources=['test_target_filter_task_mixin.py'],
  dependencies = [
    'src/python/pants/backend/graph_info/tasks',
    'src/python/pants/build_graph',
    'tests/python/pants_test/tasks:task_test_base',
  ],
)
