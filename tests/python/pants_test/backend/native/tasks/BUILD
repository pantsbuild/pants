python_tests(
  dependencies=[
    ':native_task_test_base',
    'src/python/pants/backend/native/targets',
    'src/python/pants/backend/native/tasks',
  ],
  tags={'platform_specific_behavior', 'partially_type_checked'},
  timeout=400,
)

python_library(
  name='native_task_test_base',
  sources=['native_task_test_base.py'],
  dependencies=[
    'src/python/pants/backend/native',
    'src/python/pants/backend/native/targets',
    'src/python/pants/backend/python/tasks',
    'src/python/pants/testutil:task_test_base',
  ],
  tags = {"partially_type_checked"},
)
