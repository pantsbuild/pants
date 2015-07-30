python_test_suite(
  name = 'all',
  dependencies = [
    ':checkstyle',
  ]
)

python_test_suite(
  name = 'checkstyle',
  dependencies = [
    ':test_common',
    ':test_noqa',
    'tests/python/pants_test/backend/python/tasks/checkstyle/plugins:all',
  ]
)

python_tests(
  name = 'test_common',
  sources = ['test_common.py'],
  dependencies = [
    'src/python/pants/backend/python/tasks/checkstyle:all',
  ]
)

python_tests(
  name = 'test_noqa',
  sources = ['test_noqa.py'],
  dependencies = [
    'src/python/pants/backend/python/tasks/checkstyle:all',
  ]
)
