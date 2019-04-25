# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  name='interpreter_cache_test_mixin',
  sources=['interpreter_cache_test_mixin.py'],
  dependencies = [
    'src/python/pants/util:collections_abc_backport',
    '3rdparty/python:future',
  ]
)

python_library(
  name='python_task_test_base',
  sources=['python_task_test_base.py'],
  dependencies=[
    ':interpreter_cache_test_mixin',
    '3rdparty/python:future',
    'src/python/pants/backend/python:plugin',
    'src/python/pants/backend/python/targets',
    'src/python/pants/build_graph',
    'src/python/pants/subsystem',
    'tests/python/pants_test:task_test_base'
  ]
)

python_tests(
  name = 'build_local_python_distributions',
  sources = ['test_build_local_python_distributions.py'],
  dependencies = [
    '3rdparty/python:pex',
    '3rdparty/python/twitter/commons:twitter.common.collections',
    'src/python/pants/backend/python:python_requirement',
    'src/python/pants/backend/python/targets',
    'tests/python/pants_test/backend/python/tasks/util',
  ],
)

python_tests(
  name = 'build_local_python_distributions_integration',
  sources = ['test_build_local_python_distributions_integration.py'],
  dependencies = [
    'src/python/pants/util:collections',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:process_handler',
    'tests/python/pants_test:int-test',
    'tests/python/pants_test/testutils:py2_compat',
  ],
  tags = {'integration'},
  timeout=450
)

python_tests(
  name = 'gather_sources',
  sources = ['test_gather_sources.py'],
  dependencies = [
    '3rdparty/python:future',
    '3rdparty/python:pex',
    'src/python/pants/backend/python:interpreter_cache',
    'src/python/pants/backend/python/subsystems',
    'src/python/pants/backend/python/targets',
    'src/python/pants/backend/python/tasks',
    'src/python/pants/build_graph',
    'src/python/pants/source',
    'src/python/pants/util:contextutil',
    'tests/python/pants_test:task_test_base',
  ],
)

python_tests(
  name = 'interpreter_selection_integration',
  sources = ['test_interpreter_selection_integration.py'],
  dependencies = [
    '3rdparty/python:pex',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:process_handler',
    'tests/python/pants_test:int-test',
    'tests/python/pants_test/backend/python:interpreter_selection_utils',
  ],
  tags = {'integration'},
  timeout=240,
)

python_tests(
  name = 'isort_run',
  sources = ['test_isort_run.py'],
  dependencies = [
    '3rdparty/python:future',
    'src/python/pants/backend/python/tasks',
    'src/python/pants/base:exceptions',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:process_handler',
    'tests/python/pants_test/backend/python:interpreter_selection_utils',
    ':python_task_test_base',
  ],
)

python_tests(
  name = 'isort_run_integration',
  sources = ['test_isort_run_integration.py'],
  dependencies = [
    'src/python/pants/backend/python/tasks',
    'tests/python/pants_test:int-test',
  ],
  tags = {'integration'},
)

python_tests(
  name = 'pytest_run',
  sources = ['test_pytest_run.py'],
  dependencies = [
    '3rdparty/python:coverage',
    '3rdparty/python:future',
    'src/python/pants/backend/python/tasks',
    'src/python/pants/base:exceptions',
    'src/python/pants/build_graph',
    'src/python/pants/source',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'src/python/pants/util:py2_compat',
    'src/python/pants/util:process_handler',
    'tests/python/pants_test:task_test_base',
    'tests/python/pants_test/subsystem:subsystem_utils',
    ':python_task_test_base',
  ],
  timeout=240,
)

python_tests(
  name = 'pytest_run_integration',
  sources = ['test_pytest_run_integration.py'],
  dependencies = [
    'src/python/pants/util:contextutil',
    'tests/python/pants_test:int-test',
    'tests/python/pants_test/backend/python:interpreter_selection_utils',
    'tests/python/pants_test/testutils:pexrc_util',
  ],
  tags = {'integration'},
  timeout=240,
)

python_tests(
  name = 'python_binary_create',
  sources = ['test_python_binary_create.py'],
  dependencies = [
    '3rdparty/python:future',
    'src/python/pants/backend/python/tasks',
    'src/python/pants/base:run_info',
    'src/python/pants/build_graph',
    'src/python/pants/util:process_handler',
    ':python_task_test_base',
  ],
)

python_tests(
  name = 'python_binary_integration',
  sources = ['test_python_binary_integration.py'],
  dependencies = [
    '3rdparty/python:pex',
    'src/python/pants/util:contextutil',
    'tests/python/pants_test:int-test',
  ],
  tags = {'integration'},
  timeout=240
)

python_tests(
  name = 'python_repl',
  sources = ['test_python_repl.py'],
  dependencies = [
    '3rdparty/python:future',
    'src/python/pants/backend/python/tasks',
    'src/python/pants/base:exceptions',
    'src/python/pants/build_graph',
    'src/python/pants/task',
    'src/python/pants/util:contextutil',
    ':python_task_test_base',
  ],
)

python_tests(
  name = 'python_repl_integration',
  sources = ['test_python_repl_integration.py'],
  dependencies = [
    'tests/python/pants_test:int-test',
    'tests/python/pants_test/testutils:py2_compat',
  ],
  tags = {'integration'},
  timeout=120,
)

python_tests(
  name = 'python_run_integration',
  sources = ['test_python_run_integration.py'],
  dependencies = [
    '3rdparty/python:pex',
    'src/python/pants/util:contextutil',
    'tests/python/pants_test:int-test',
    'tests/python/pants_test/backend/python:interpreter_selection_utils',
    'tests/python/pants_test/testutils:pexrc_util',
  ],
  tags = {'integration'},
  timeout=240
)

python_tests(
  name = 'python_tool',
  sources = ['test_python_tool.py'],
  dependencies = [
    'src/python/pants/backend/python/subsystems',
    'src/python/pants/backend/python/tasks',
    'src/python/pants/task',
    'src/python/pants/util:contextutil',
    ':python_task_test_base',
  ],
)

python_tests(
  name = 'resolve_requirements',
  sources = ['test_resolve_requirements.py'],
  dependencies = [
    '3rdparty/python:future',
    '3rdparty/python:pex',
    'src/python/pants/backend/python:interpreter_cache',
    'src/python/pants/backend/python:python_requirement',
    'src/python/pants/backend/python/subsystems',
    'src/python/pants/backend/python/targets',
    'src/python/pants/backend/python/tasks',
    'src/python/pants/base:build_environment',
    'src/python/pants/task',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:process_handler',
    'tests/python/pants_test:task_test_base',
  ],
)

python_tests(
  name = 'select_interpreter',
  sources = ['test_select_interpreter.py'],
  dependencies = [
    '3rdparty/python:future',
    '3rdparty/python:mock',
    '3rdparty/python:pex',
    'src/python/pants/backend/python:interpreter_cache',
    'src/python/pants/backend/python/subsystems',
    'src/python/pants/backend/python/targets',
    'src/python/pants/backend/python/tasks',
    'src/python/pants/base:exceptions',
    'src/python/pants/util:dirutil',
    'tests/python/pants_test:task_test_base',
  ],
)

python_tests(
  name = 'setup_py',
  sources = ['test_setup_py.py'],
  dependencies = [
    '3rdparty/python:future',
    '3rdparty/python:mock',
    '3rdparty/python:pex',
    '3rdparty/python/twitter/commons:twitter.common.collections',
    '3rdparty/python/twitter/commons:twitter.common.dirutil',
    'src/python/pants/backend/python/subsystems',
    'src/python/pants/backend/python/targets',
    'src/python/pants/backend/python/tasks',
    'src/python/pants/base:exceptions',
    'src/python/pants/build_graph',
    'src/python/pants/fs',
    'src/python/pants/util:collections_abc_backport',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'tests/python/pants_test/backend/python:interpreter_selection_utils',
    'tests/python/pants_test/subsystem:subsystem_utils',
    ':python_task_test_base',
  ],
)

python_tests(
  name = 'setup_py_integration',
  sources = ['test_setup_py_integration.py'],
  dependencies = [
    'tests/python/pants_test/backend/python:pants_requirement_integration_test_base',
  ],
  tags = {'integration'},
  timeout=240,
)


python_tests(
  name = 'unpack_wheels',
  sources = ['test_unpack_wheels.py'],
  dependencies = [
    'src/python/pants/backend/python:python_requirement',
    'src/python/pants/backend/python/targets',
    'src/python/pants/backend/python/tasks',
    'src/python/pants/task',
    'src/python/pants/util:collections',
    'tests/python/pants_test:task_test_base',
  ],
)
