python_test_suite(
  name='all',
  dependencies=[
    ':python_eval'
  ]
)

python_tests(
  name='python_eval',
  sources=['test_python_eval.py'],
  dependencies=[
    'src/python/pants/backend/python/targets:python',
    'src/python/pants/backend/python/tasks:python',
    'src/python/pants/base:build_file_aliases',
    'tests/python/pants_test/tasks:base'
  ]
)