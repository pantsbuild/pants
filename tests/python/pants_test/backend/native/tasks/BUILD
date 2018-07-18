python_tests(
  dependencies=[
    ':native_task_test_base',
    'src/python/pants/backend/native/targets',
    'src/python/pants/backend/native/tasks',
  ],
  tags={'platform_specific_behavior'},
)

python_library(
  name='native_task_test_base',
  sources=['native_task_test_base.py'],
  dependencies=[
    'src/python/pants/backend/native',
    'src/python/pants/backend/native/targets',
    'tests/python/pants_test:task_test_base',
  ],
)