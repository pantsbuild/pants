python_test_suite(
  name = 'all',
  dependencies = [
    ':checkstyle',
  ]
)

python_tests(
  name = 'checkstyle',
  sources = globs('*.py'),
  dependencies = [
    '3rdparty/python:mock',
    'src/python/pants/backend/python/tasks/checkstyle:all',
    'tests/python/pants_test/backend/python/tasks:python_task_test_base',
    'tests/python/pants_test:base_test',
  ]
)
