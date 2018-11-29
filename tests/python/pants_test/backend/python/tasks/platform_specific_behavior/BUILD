python_tests(
  sources=globs('test_*.py', exclude=[globs('*_integration.py')]),
  dependencies = [
    '3rdparty/python:future',
    '3rdparty/python/twitter/commons:twitter.common.collections',
    'src/python/pants/backend/native/targets',
    'src/python/pants/backend/python/targets',
    'src/python/pants/util:contextutil',
    'tests/python/pants_test/backend/python/tasks/util',
  ],
  tags={'platform_specific_behavior'},
)

python_tests(
  name='integration',
  sources=globs('*_integration.py'),
  dependencies=[
    '3rdparty/python:future',
    'src/python/pants/backend/native/config',
    'src/python/pants/util:collections',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'src/python/pants/util:process_handler',
    'tests/python/pants_test:int-test',
    'tests/python/pants_test/backend/python/tasks:python_task_test_base',
    'tests/python/pants_test/testutils:py2_compat',
  ],
  tags={'platform_specific_behavior', 'integration'},
  timeout=2400,
)
