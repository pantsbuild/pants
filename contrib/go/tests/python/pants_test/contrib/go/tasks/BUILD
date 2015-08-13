target(
  name='all',
  dependencies=[
    ':unit',
    ':integration',
  ]
)

target(
  name='unit',
  dependencies=[
    ':go_workspace_task',
    ':go_compile',
    ':go_fetch',
  ]
)

target(
  name='integration',
  dependencies=[
    ':go_compile_integration',
    ':go_test_integration',
    ':go_run_integration',
    ':go_fetch_integration',
  ]
)

python_tests(
  name='go_workspace_task',
  sources=['test_go_workspace_task.py'],
  dependencies=[
    'tests/python/pants_test/tasks:task_test_base',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'contrib/go/src/python/pants/contrib/go/targets:go_library',
    'contrib/go/src/python/pants/contrib/go/targets:go_remote_library',
    'contrib/go/src/python/pants/contrib/go/tasks:go_workspace_task',
  ]
)

python_tests(
  name='go_compile',
  sources=['test_go_compile.py'],
  dependencies=[
    'tests/python/pants_test/tasks:task_test_base',
    'src/python/pants/util:dirutil',
    'contrib/go/src/python/pants/contrib/go/targets:go_library',
    'contrib/go/src/python/pants/contrib/go/tasks:go_compile',
  ]
)

python_tests(
  name='go_fetch',
  sources=['test_go_fetch.py'],
  dependencies=[
    'tests/python/pants_test/tasks:task_test_base',
    'src/python/pants/util:contextutil',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:target',
    'src/python/pants/base:source_root',
    'contrib/go/src/python/pants/contrib/go/targets:go_remote_library',
    'contrib/go/src/python/pants/contrib/go/tasks:go_fetch',
  ]
)

python_tests(
  name='go_compile_integration',
  sources=['test_go_compile_integration.py'],
  dependencies=[
    'contrib/go/src/python/pants/contrib/go/tasks:go_task',
    'src/python/pants/util:contextutil',
    'tests/python/pants_test:int-test',
    ':go_tool',
  ]
)

python_tests(
  name='go_test_integration',
  sources=['test_go_test_integration.py'],
  dependencies=[
    'tests/python/pants_test:int-test',
    ':go_tool',
  ]
)

python_tests(
  name='go_run_integration',
  sources=['test_go_run_integration.py'],
  dependencies=[
    'tests/python/pants_test:int-test',
  ]
)

python_tests(
  name='go_fetch_integration',
  sources=['test_go_fetch_integration.py'],
  dependencies=[
    'src/python/pants/util:dirutil',
    'src/python/pants/base:build_environment',
    'tests/python/pants_test:int-test',
  ]
)

python_library(
  name='go_tool',
  sources=['go_tool.py'],
)
